"""The measure mode, per-state waits, guard polling and configurable route of the recon driver."""

from __future__ import annotations

import json

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
        # The desktop around the emulator changes on every grab; only the crop
        # is the Amiga screen, as `WinGuest.capture` leaves it.
        self.grabs = getattr(self, "grabs", 0) + 1
        raw.write_bytes(f"grab {self.grabs}".encode())
        cropped.write_bytes(f"frame {shown}".encode())

    def grab(self, state, raw, cropped, timeout=None):
        self.calls.append(("grab", state))
        self.at.append((state, self.clock.now))
        self.grabs = getattr(self, "grabs", 0) + 1
        raw.write_bytes(f"grab {self.grabs}".encode())
        cropped.write_bytes(f"frame {self.presses}".encode())
        return True


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
    assert waits["party_menu"] == 15 and waits["load_picker"] == 20
    assert waits["loaded_menu"] == 20 and waits["items"] == 15
    # Boot 2 measured the version line and the bar on one screen, so the
    # route has no separate version state to wait 50 s for.
    assert "version" not in waits


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
    assert guest.calls.count(("grab", "01-version")) == 4
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
            disk = AmigaDisk(self.remote[self.drives[0]])
            disk.write_file("/SAVE/savgamB.sav", b"engine wrote B")
            self.remote[self.drives[0]] = disk.to_bytes()


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


class AlteringGuest(ScreenGuest):
    """The guest changes one drive on a key that is not a write key."""

    def __init__(self, clock, drive, change):
        super().__init__(clock)
        self.drive, self.change = drive, change

    def press(self, holder, key, timeout=None):
        super().press(holder, key, timeout)
        if key == "X":
            remote = self.drives[self.drive]
            disk = AmigaDisk(self.remote[remote])
            self.change(disk)
            self.remote[remote] = disk.to_bytes()


def test_measure_fails_when_the_guest_alters_disk_b(tmp_path, clock):
    guest = AlteringGuest(clock, 1, lambda d: d.make_dir("/EXTRA"))
    result = _measure(tmp_path, guest, route=(("RET", "version"), ("X", "items")))
    assert result["df1_unchanged"] is False and result["df0_unchanged"] is True
    assert result["slot_b_sha256"] is None and result["route_changed"] is True
    assert result["success"] is False


def test_measure_fails_when_the_guest_alters_the_boot_disk(tmp_path, clock):
    # A file other than savgamB.sav, so only the changed DF0 can fail the run.
    guest = AlteringGuest(clock, 0, lambda d: d.write_file("/SAVE/other.sav", b"x"))
    result = _measure(tmp_path, guest, route=(("RET", "version"), ("X", "items")))
    assert result["df0_unchanged"] is False and result["df1_unchanged"] is True
    assert result["slot_b_sha256"] is None and result["route_changed"] is True
    assert result["success"] is False


class PartialGuards:
    """A guard map holding only some states, each recognised on its nth grab."""

    def __init__(self, after):
        self.after, self.seen = dict(after), {}

    def __contains__(self, state):
        return state in self.after

    def __call__(self, state, path):
        assert state in self.after, f"{state} has no guard and must not be checked"
        self.seen[state] = self.seen.get(state, 0) + 1
        need = self.after[state]
        return need is not None and self.seen[state] >= need


def test_the_route_leaves_the_play_bar_by_its_letter():
    keys = [key for key, _ in amigasecretsave.ROUTE]
    assert amigasecretsave.ROUTE[:3] == (
        ("P", "party_menu"), ("L", "load_picker"),
        (amigasecretsave.SLOT_LETTER, "loaded_menu"))
    assert "RET" not in keys and "B" not in keys


def test_guarded_route_states_are_grabbed_and_only_the_last_shot_is_settled(
        tmp_path, clock):
    guest = ScreenGuest(clock)
    amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=lambda s, p: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path))
    states = ["title"] + [f"{n:02d}-{s}" for n, (_, s) in
                          enumerate(amigasecretsave.ROUTE, 1)]
    assert [c[1] for c in guest.calls if c[0] == "grab"] == states
    assert [c[1] for c in guest.calls if c[0] == "capture"] == ["post-write"]


def test_post_write_capture_that_never_settles_is_reported(tmp_path, clock):
    class NeverStill(ScreenGuest):
        def capture(self, state, raw, cropped, timeout=None):
            super().capture(state, raw, cropped, timeout)
            raise amigasecretsave.RouteError(f"{state} did not settle inside 120s")

    guest = NeverStill(clock)
    result = amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=lambda s, p: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path))
    assert _keys(guest) == [k for k, _ in amigasecretsave.ROUTE] + ["B"]
    assert "post-write did not settle" in result["error"]


def test_a_grab_with_no_window_is_polled_again_and_never_reaches_the_guard(
        tmp_path, clock):
    class WindowLate(ScreenGuest):
        blind = 3

        def grab(self, state, raw, cropped, timeout=None):
            if state == "title" and self.blind:
                self.blind -= 1
                self.calls.append(("grab", state))
                raw.write_bytes(b"desktop")
                return False
            return super().grab(state, raw, cropped, timeout)

    def guard(state, path):
        # A missing crop raises FileNotFoundError, as the real guard does.
        path.read_bytes()
        return True

    guest = WindowLate(clock)
    result = amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=guard, holder="wish672-test",
        audio_proof=_audio_proof(tmp_path), route=(("RET", "version"),))
    assert guest.calls.count(("grab", "title")) == 4
    assert "FileNotFoundError" not in result["error"]
    assert [e["state"] for e in result["events"]
            if e.get("recognized")] == ["title", "01-version"]
    assert _keys(guest) == ["RET", "B"]


def test_a_grab_is_bounded_by_one_shot_and_the_deadline(tmp_path, clock):
    class Timed(ScreenGuest):
        timeouts: list = []

        def grab(self, state, raw, cropped, timeout=None):
            self.timeouts.append(timeout)
            return super().grab(state, raw, cropped, timeout)

    guest = Timed(clock)
    guest.timeouts = []
    amigasecretsave.run_recon(
        _prepared(tmp_path), guest=guest, guard=lambda s, p: True,
        holder="wish672-test", audio_proof=_audio_proof(tmp_path))
    assert guest.timeouts
    assert all(0 < t <= amigasecretsave.SHOT_SECONDS for t in guest.timeouts)


def test_measure_waits_for_the_title_guard_before_the_first_key(tmp_path, clock):
    guest = ScreenGuest(clock)
    guards = PartialGuards({"title": 3})
    result = _measure(tmp_path, guest, guard=guards)
    first = next(i for i, c in enumerate(guest.calls) if c[0] == "press")
    assert [c for c in guest.calls[:first] if c[0] in ("grab", "capture")] == [
        ("grab", "00-boot-00"), ("grab", "00-boot-01"), ("grab", "00-boot-01")]
    assert clock.sleeps[:2] == [amigasecretsave.TITLE_POLL] * 2
    recognized = [e for e in result["events"] if e.get("recognized") == "title"]
    assert len(recognized) == 1
    assert (tmp_path / "recon1" / "shots" / "00-boot-01.png").exists()
    assert _keys(guest) == [k for k, _ in amigasecretsave.ROUTE]
    assert result["success"] is True


def test_measure_presses_nothing_when_the_title_is_never_recognized(tmp_path, clock):
    guest = ScreenGuest(clock)
    result = _measure(tmp_path, guest, guard=PartialGuards({"title": None}))
    assert "title screen was not recognized within 180s" in result["error"]
    assert _keys(guest) == []
    assert result["success"] is False
    assert _cleanup_ran(guest)


def test_measure_stops_at_a_guarded_state_it_never_recognizes(tmp_path, clock):
    guest = ScreenGuest(clock)
    result = _measure(tmp_path, guest,
                      guard=PartialGuards({"title": 1, "party_menu": None}))
    assert "party_menu screen was not recognized" in result["error"]
    assert _keys(guest) == ["P"]
    assert (tmp_path / "recon1" / "shots" / "01-party_menu.png").exists()
    assert result["success"] is False
    assert _cleanup_ran(guest)


def _image(path, colour, patch=None):
    from PIL import Image

    image = Image.new("RGB", (720, 568), colour)
    if patch:
        image.paste(patch[1], patch[0])
    image.save(path)
    return path


def _full_map(tmp_path, drop=()):
    shot = _image(tmp_path / "shot.png", (0, 51, 102))
    rule = amigasecretsave.guard_rule(shot, (0, 0, 8, 8))
    states = {"title", *(s for _, s in amigasecretsave.ROUTE)} - set(drop)
    path = tmp_path / "guards.json"
    path.write_text(json.dumps({s: rule for s in states}))
    return path


def test_a_guard_map_for_the_measured_route_loads(tmp_path):
    guards = amigasecretsave.PixelGuards(_full_map(tmp_path))
    assert "title" in guards and "party_menu" in guards
    assert "version" not in guards


def test_guarded_mode_refuses_a_guard_map_missing_a_route_state(tmp_path):
    guards = amigasecretsave.PixelGuards(_full_map(tmp_path, drop=("items",)))
    guest = FailedPostWriteGuest()
    with pytest.raises(amigasecretsave.RouteError, match="lacks.*items"):
        amigasecretsave.run_recon(
            _prepared(tmp_path), guest=guest, guard=guards,
            holder="wish672-test", audio_proof=_audio_proof(tmp_path))
    assert guest.calls == []


def test_a_guard_rule_matches_its_own_box_and_not_a_neighbour(tmp_path):
    bar = ((60, 400, 300, 430), (238, 238, 238))
    title = _image(tmp_path / "title.png", (0, 51, 102), bar)
    story = _image(tmp_path / "story.png", (0, 51, 102))
    moved = _image(tmp_path / "moved.png", (0, 51, 102),
                   ((60, 401, 300, 431), (238, 238, 238)))
    rule = amigasecretsave.guard_rule(title, (60, 400, 300, 430))
    path = tmp_path / "guards.json"
    path.write_text(json.dumps({"title": rule}))
    guards = amigasecretsave.PixelGuards(path)
    assert guards("title", title)
    assert not guards("title", story) and not guards("title", moved)
    assert not guards("credits", title)


def test_the_guard_command_refuses_a_box_that_matches_a_neighbour(tmp_path, capsys):
    bar = ((60, 400, 300, 430), (238, 238, 238))
    title = _image(tmp_path / "title.png", (0, 51, 102), bar)
    story = _image(tmp_path / "story.png", (0, 51, 102))
    out = tmp_path / "guards.json"
    common = ["guard", "--state", "title", "--crop", str(title), "--out", str(out)]
    # The blue corner is the same on both screens, so it cannot tell them apart.
    assert amigasecretsave.main(
        common + ["--box", "0,0,40,40", "--unlike", str(story)]) == 2
    assert "also matches" in capsys.readouterr().err and not out.exists()
    assert amigasecretsave.main(
        common + ["--box", "50,400,300,430", "--unlike", str(story)]) == 0
    written = json.loads(out.read_text())
    assert written["title"]["box"] == [50, 400, 300, 430]
    assert amigasecretsave.PixelGuards(out)("title", title)


def test_a_custom_route_with_b_never_presses_it_in_measure_mode(tmp_path, clock):
    guest = ScreenGuest(clock)
    route = (("P", "party_menu"), ("B", "save_picker"), ("X", "items"))
    result = _measure(tmp_path, guest, route=route, write_keys=("W",))
    assert _keys(guest) == ["P"]
    assert {"skipped_write_key": "B", "step": 2} in result["events"]
    assert result["route_changed"] is False and result["success"] is False


def test_the_built_in_route_contains_no_b():
    assert "B" not in [key for key, _ in amigasecretsave.ROUTE]


def _rules(tmp_path, rule):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"title": rule}))
    return path


@pytest.mark.parametrize("rule", [
    {"box": [0, 0, 8, 8], "sha256": "ab" * 31},
    {"box": [0, 0, 8, 8], "sha256": "AB" * 32},
    {"box": "0,0,8,8", "sha256": "ab" * 32},
    {"sha256": "ab" * 32},
    ["box"],
])
def test_a_malformed_guard_rule_is_refused_on_load(tmp_path, rule):
    with pytest.raises(amigasecretsave.RouteError, match="title"):
        amigasecretsave.PixelGuards(_rules(tmp_path, rule))


@pytest.mark.parametrize("box", [[0, 0, 8], [0, 0, 8, 8, 9], [0, 0, 721, 8],
                                 [0, 0, 8, 569], [8, 0, 8, 8], [-1, 0, 8, 8]])
def test_a_guard_box_with_the_wrong_numbers_or_outside_the_image_is_refused(
        tmp_path, box):
    shot = _image(tmp_path / "shot.png", (0, 51, 102))
    with pytest.raises(amigasecretsave.RouteError, match="invalid crop box"):
        amigasecretsave.guard_rule(shot, box)


def _guard_args(tmp_path, *extra, box="50,400,300,430"):
    bar = ((60, 400, 300, 430), (238, 238, 238))
    title = _image(tmp_path / "title.png", (0, 51, 102), bar)
    out = tmp_path / "guards.json"
    return ["guard", "--state", "title", "--crop", str(title), "--out", str(out),
            "--box", box, *extra], out


def test_the_guard_command_refuses_a_one_colour_box(tmp_path, capsys):
    args, out = _guard_args(tmp_path, box="0,0,40,40")
    assert amigasecretsave.main(args) == 2
    assert "one colour" in capsys.readouterr().err and not out.exists()


def test_the_guard_command_will_not_replace_a_rule_unless_asked(tmp_path, capsys):
    args, out = _guard_args(tmp_path)
    assert amigasecretsave.main(args) == 0
    before = out.read_text()
    other = _image(tmp_path / "other.png", (0, 51, 102),
                   ((60, 400, 300, 430), (200, 10, 10)))
    again = ["guard", "--state", "title", "--crop", str(other), "--out", str(out),
             "--box", "50,400,300,430"]
    assert amigasecretsave.main(again) == 2
    assert "--replace" in capsys.readouterr().err and out.read_text() == before
    assert amigasecretsave.main(again + ["--replace"]) == 0
    assert out.read_text() != before


def _failing_replace(tmp_path, monkeypatch):
    args, out = _guard_args(tmp_path)
    assert amigasecretsave.main(args) == 0
    other = _image(tmp_path / "other.png", (0, 51, 102),
                   ((60, 400, 300, 430), (200, 10, 10)))
    again = ["guard", "--state", "title", "--crop", str(other), "--out", str(out),
             "--box", "50,400,300,430", "--replace"]

    def boom(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(amigasecretsave.os, "replace", boom)
    return again, out


def test_the_guard_command_writes_atomically(tmp_path, monkeypatch):
    again, out = _failing_replace(tmp_path, monkeypatch)
    before = out.read_text()
    assert amigasecretsave.main(again) == 2
    assert out.read_text() == before


def test_a_failed_guard_write_leaves_no_temp_file(tmp_path, monkeypatch):
    again, out = _failing_replace(tmp_path, monkeypatch)
    assert amigasecretsave.main(again) == 2
    assert not out.with_name(out.name + ".tmp").exists()
