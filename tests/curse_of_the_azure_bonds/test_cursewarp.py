"""`tools/curse_of_the_azure_bonds/curseload.py`'s world entry, which `cursewarp.py` imports, has the identical vulnerability
`tests/secret_of_the_silver_blades/test_ssbwarp.py` covers for Silver Blades (#568, general defect;
`#334`'s own Silver Blades half is where it was first traced).

Escape is VICE's RUN/STOP key, which aborts a KERNAL `LOAD` still running.
`enter_world` used to send it after any `STUCK` (15s) seconds of an
unchanged screen -- exempting only a literally blank one, not a screen
showing old content while a slow ECL load runs underneath it. The fix gates
that Escape on `idle_in_key_window`, a single PC read against the same
`key_wait`/`key_fetch` windows `wait_idle` already polls after a warp.

**`addr` is optional on `enter_world` here**, because `tools/gui/livecheck.py`,
`tools/c64/inventorycheck.py` and `tools/curse_of_the_azure_bonds/cursecheck.py` -- none of them this
file's own -- call it without one; those calls keep the old unconditional
Escape.
"""

from __future__ import annotations

from contextlib import contextmanager

from tools.curse_of_the_azure_bonds import curseload as CURSE


class FakeRegs:
    def __init__(self, pc):
        self.pc = pc

    def get(self, rid):
        return self.pc


class FakeMon:
    def __init__(self, pc):
        self._pc_register = 0x90
        self._pc = pc

    def registers(self):
        return FakeRegs(self._pc)


class FakeSess:
    """Just enough of `Session` for `idle_in_key_window`: a monitor context
    manager."""

    def __init__(self, pc):
        self.pc = pc

    @contextmanager
    def mon(self, timeout):
        yield FakeMon(self.pc)


class Addr:
    key_wait = (0x1000, 0x1010)
    key_fetch = (0x2000, 0x2010)


def test_idle_in_key_window_confirms_a_pc_genuinely_in_the_window():
    sess = FakeSess(pc=0x2005)
    assert CURSE.idle_in_key_window(sess, Addr()) == 0x2005


def test_idle_in_key_window_rejects_a_pc_outside_both_windows():
    """The load-in-progress case: the screen has not changed, but the PC is
    off in the KERNAL loader rather than waiting in a key window."""
    sess = FakeSess(pc=0xE000)
    assert CURSE.idle_in_key_window(sess, Addr()) is None


class FakeScreen:
    def __init__(self, text, bar=None):
        self._text = text
        self._bar = bar if bar is not None else text

    def text(self):
        return self._text

    def row(self, n):
        return self._bar


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


class StuckSess:
    """A screen that never changes and never answers a prompt -- the state
    `enter_world` used to escape out of unconditionally."""

    def __init__(self):
        self.logged: list[str] = []
        self.kbd_sent: list[str] = []

        outer = self

        class Kbd:
            def key(self, name):
                outer.kbd_sent.append(name)

        self.kbd = Kbd()

    def screen(self):
        return FakeScreen("SOME MENU", bar="SOME MENU")

    def iec_stall_check(self):
        return False

    def stall_capture(self):
        return "captured"

    def handle_prompt(self, s=None):
        return False

    def log(self, *a):
        self.logged.append(" ".join(str(x) for x in a))


def _make_stuck_sess():
    sess = StuckSess()
    return sess, sess.kbd_sent


def test_enter_world_does_not_escape_a_screen_stuck_by_a_slow_load(
        monkeypatch):
    """Red without the fix: `idle_in_key_window` returning None must not
    stop `enter_world` from pressing Escape into a load still running."""
    clock = FakeClock()
    monkeypatch.setattr(CURSE.time, "time", clock.time)
    monkeypatch.setattr(CURSE.time, "sleep", clock.sleep)
    monkeypatch.setattr(CURSE, "idle_in_key_window",
                        lambda sess, addr: None)
    sess, sent = _make_stuck_sess()
    ok = CURSE.enter_world(sess, Addr(), timeout=40.0)
    assert ok is False
    assert "Escape" not in sent


def test_enter_world_escapes_once_the_pc_is_genuinely_idle(monkeypatch):
    """The other half: a machine really sitting in a key window still gets
    Escape as before."""
    clock = FakeClock()
    monkeypatch.setattr(CURSE.time, "time", clock.time)
    monkeypatch.setattr(CURSE.time, "sleep", clock.sleep)
    monkeypatch.setattr(CURSE, "idle_in_key_window",
                        lambda sess, addr: 0x1005)
    sess, sent = _make_stuck_sess()
    ok = CURSE.enter_world(sess, Addr(), timeout=40.0)
    assert ok is False
    assert "Escape" in sent


class PressContinueSess:
    """Curse's own opening page -- `PRESS BUTTON OR RETURN TO CONTINUE.` on
    row 24 -- with the world already reachable behind it. A Return dismisses
    it; anything else leaves it sitting there until `enter_world`'s STUCK
    branch or the timeout takes over."""

    def __init__(self):
        self.logged: list[str] = []
        self.kbd_sent: list[str] = []
        self.dismissed = False

        outer = self

        class Kbd:
            def key(self, name):
                outer.kbd_sent.append(name)

        self.kbd = Kbd()

    def screen(self):
        if self.dismissed:
            return FakeScreen("ENCAMP", bar="ENCAMP")
        return FakeScreen("SOME SCENE\nPRESS BUTTON OR RETURN TO CONTINUE.",
                          bar="PRESS BUTTON OR RETURN TO CONTINUE.")

    def iec_stall_check(self):
        return False

    def stall_capture(self):
        return "captured"

    def handle_prompt(self, s=None):
        return False

    def press_kernal(self, code):
        self.dismissed = True

    def log(self, *a):
        self.logged.append(" ".join(str(x) for x in a))


def test_enter_world_dismisses_curses_own_press_continue_screen(monkeypatch):
    """Red without the fix: the PRESS screen falls through to the STUCK
    branch, which only escapes when the PC is confirmed idle -- and here it
    never is, since `idle_in_key_window` is not exercised at all without the
    new branch pressing Return first. Without the fix `enter_world` never
    reaches ENCAMP within the timeout."""
    clock = FakeClock()
    monkeypatch.setattr(CURSE.time, "time", clock.time)
    monkeypatch.setattr(CURSE.time, "sleep", clock.sleep)
    sess = PressContinueSess()
    ok = CURSE.enter_world(sess, Addr(), timeout=40.0)
    assert ok is True
    assert "Escape" not in sess.kbd_sent


def test_enter_world_without_addr_keeps_the_old_unconditional_escape(
        monkeypatch):
    """The three callers that do not pass `addr` -- `tools/gui/livecheck.py`,
    `tools/c64/inventorycheck.py`, `tools/curse_of_the_azure_bonds/cursecheck.py` -- must see the same
    behaviour as before this fix, since none of them is this ticket's file
    to change."""
    clock = FakeClock()
    monkeypatch.setattr(CURSE.time, "time", clock.time)
    monkeypatch.setattr(CURSE.time, "sleep", clock.sleep)
    sess, sent = _make_stuck_sess()
    ok = CURSE.enter_world(sess, timeout=40.0)
    assert ok is False
    assert "Escape" in sent


# ---- `cursewarp.py --camp-save` ----------------------------------------

import contextlib  # noqa: E402
import json  # noqa: E402
import types  # noqa: E402

import pytest  # noqa: E402

from goldbox.d64 import D64  # noqa: E402
from tools.curse_of_the_azure_bonds import cursewarp as WARP  # noqa: E402


def disk_bytes(tmp_path):
    return (tmp_path / "slot.D64").read_bytes()


class _SaveMon:
    def peek(self, at):
        return 0x10

    def read(self, at, n):
        return bytes(range(n))


def _run_with_fakes(monkeypatch, tmp_path, save_ok=True, camp_save="x",
                    arrival_choice="", bars=None, save_raises=None,
                    combat_on=None):
    """`run` with every machine call faked.

    `bars` is what row 24 says, in order: each entry is held until the call
    named in its second field (`press_bar`, `press_kernal` or `leave_move`)
    moves it on, or for good when that field is None; an optional third
    field keeps the row up for that many more reads after the call.  `combat_on` is a bar at which
    `in_combat` starts answering True.
    """
    calls: list[str] = []
    script = list(bars or [])
    disk = tmp_path / "slot.D64"
    D64.blank("GAMEWRITTEN").save(disk)
    source = tmp_path / "source.D64"
    source.write_bytes(b"source")
    dest = tmp_path / "yulash.D64"

    class Sess:
        save_disk = str(disk)

        def __init__(self, *a, **k):
            pass

        def boot(self):
            return True

        def patch_disk_prompt(self):
            pass

        def settle(self, n):
            pass

        def screen(self):
            if not script:
                return None
            bar = script[0][0]
            if script[0][1] == "read":
                left = script[0][2] - 1
                if left:
                    script[0] = (bar, "read", left)
                else:
                    script.pop(0)
            return FakeScreen("", bar=bar)

        def attach(self, path):
            calls.append("attach")

        def leave_move(self, tries=8):
            calls.append("leave_move")
            self._advance("leave_move")
            return True

        @contextlib.contextmanager
        def mon(self, t):
            yield _SaveMon()

        def save_game(self):
            calls.append("save_game")
            if save_raises is not None:
                raise save_raises
            return save_ok

        def _advance(self, how):
            if script and script[0][1] == how:
                linger = script[0][2] if len(script[0]) > 2 else 0
                if linger:
                    script[0] = (script[0][0], "read", linger)
                else:
                    script.pop(0)

        def in_combat(self):
            return bool(script) and script[0][0] == combat_on

        def press_bar(self, label):
            calls.append(f"press_bar:{label}")
            self._advance("press_bar")
            return True

        def press_kernal(self, code):
            calls.append("return")
            self._advance("press_kernal")

        def handle_prompt(self, s=None):
            return False

        def log(self, *a):
            pass

        def terminate(self):
            pass

        kbd = types.SimpleNamespace(screenshot=lambda p: None)

    addr = types.SimpleNamespace(
        slot=0x4BF2, indoors=0x4BE6, mode=0x7F11, describe=lambda: "",
        as_dict=lambda: {})
    monkeypatch.setattr(WARP, "Addresses", lambda *a: addr)
    monkeypatch.setattr(WARP, "curse_maps", lambda d: {})
    monkeypatch.setattr(WARP.por, "claim_slot", lambda *a, **k: types.
                        SimpleNamespace(n=1, port=1, display=1,
                                        dir=str(tmp_path)))
    monkeypatch.setattr(WARP.curserun, "stage", lambda *a: "first")
    monkeypatch.setattr(WARP.curserun, "CurseSession", Sess)
    monkeypatch.setattr(WARP, "load_curse_save", lambda s: True)
    monkeypatch.setattr(WARP, "enter_world", lambda s, a: True)
    monkeypatch.setattr(WARP, "wait_idle", lambda *a, **k: (True, 0))
    monkeypatch.setattr(WARP, "resident_geo", lambda *a: {})
    monkeypatch.setattr(WARP, "snapshot", lambda *a, **k: {
        "mode": 1, "indoors": 1, "area": 2})
    monkeypatch.setattr(WARP, "warp", lambda *a: {})
    monkeypatch.setattr(WARP.por, "INDOORS_AT", 0, raising=False)
    monkeypatch.setattr(
        WARP, "walk_proof", lambda *a: calls.append("walk_proof") or {})
    args = types.SimpleNamespace(
        out=str(tmp_path / "out"), disks=str(tmp_path), pool=None, save="",
        probe=False, force=False, geo="", via_actions=False, to=0x10,
        disk=3, camp_save=str(dest) if camp_save else "",
        arrival_choice=arrival_choice)
    clock = FakeClock()
    monkeypatch.setattr(WARP, "time", clock)
    return calls, args, dest


def test_camp_save_saves_before_the_walk_proof_and_keeps_the_disk(
        monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(monkeypatch, tmp_path)
    assert WARP.run(args) == 0
    assert calls == ["save_game", "walk_proof"]
    assert dest.read_bytes() == disk_bytes(tmp_path)
    saved = json.loads((tmp_path / "out" / "saved.json").read_text())
    assert saved["ok"] and saved["saved_sha256"]
    assert saved["peeks"]["4BF2"] == 0x10


def test_a_failed_camp_save_exits_5_and_still_walks(monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(monkeypatch, tmp_path, save_ok=False)
    assert WARP.run(args) == 5
    assert calls == ["save_game", "walk_proof"]
    assert not dest.exists()


def test_without_camp_save_nothing_is_saved(monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(monkeypatch, tmp_path,
                                        camp_save=None)
    assert WARP.run(args) == 0
    assert calls == ["walk_proof"]


def test_a_save_game_that_raises_still_writes_saved_json_and_walks(
        monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(
        monkeypatch, tmp_path,
        save_raises=RuntimeError("a snapshot was restored"))
    assert WARP.run(args) == 5
    assert calls == ["save_game", "walk_proof"]
    saved = json.loads((tmp_path / "out" / "saved.json").read_text())
    assert saved["ok"] is False
    assert "a snapshot was restored" in saved["error"]
    assert not dest.exists()


YULASH = "SNEAK IN  ASK PERMISSION  LEAVE"
STORY = "PRESS BUTTON OR RETURN TO CONTINUE."
WORLD = "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK"


def test_arrival_choice_answers_the_bar_and_its_box_before_the_save(
        monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(
        monkeypatch, tmp_path, arrival_choice="SNEAK IN",
        bars=[(YULASH, "press_bar"), (STORY, "press_kernal"), (WORLD, None)])
    assert WARP.run(args) == 0
    assert calls == ["press_bar:SNEAK IN", "return", "save_game",
                     "walk_proof"]
    arrival = json.loads((tmp_path / "out" / "arrival.json").read_text())
    assert arrival["ok"] and arrival["answered"] == YULASH
    assert arrival["area"] == 0x10
    assert dest.exists()


def test_a_fight_offered_after_the_choice_stops_with_nothing_pressed(
        monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(
        monkeypatch, tmp_path, arrival_choice="ASK PERMISSION",
        bars=[(YULASH, "press_bar"), ("RUN AWAY  FIGHT  PARLAY", None)])
    assert WARP.run(args) == 6
    assert calls == ["press_bar:ASK PERMISSION"]
    arrival = json.loads((tmp_path / "out" / "arrival.json").read_text())
    assert arrival["fight"] and not arrival["ok"]
    assert not dest.exists()


@pytest.mark.parametrize("bar", ["RUN AWAY  (FIGHT)  PARLAY",
                                 "FIGHT?  RUN AWAY"])
def test_a_fight_word_in_punctuation_still_stops_the_answerer(
        monkeypatch, tmp_path, bar):
    calls, args, dest = _run_with_fakes(
        monkeypatch, tmp_path, arrival_choice="ASK PERMISSION",
        bars=[(YULASH, "press_bar"), (bar, None)])
    assert WARP.run(args) == 6
    assert calls == ["press_bar:ASK PERMISSION"]
    arrival = json.loads((tmp_path / "out" / "arrival.json").read_text())
    assert arrival["fight"]
    assert not dest.exists()


def test_a_fight_that_starts_after_the_choice_stops_the_run(
        monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(
        monkeypatch, tmp_path, arrival_choice="SNEAK IN",
        bars=[(YULASH, "press_bar"), ("", None)], combat_on="")
    assert WARP.run(args) == 6
    assert calls == ["press_bar:SNEAK IN"]
    assert not dest.exists()


def test_an_arrival_with_no_such_choice_stops_before_saving(
        monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(
        monkeypatch, tmp_path, arrival_choice="SNEAK IN",
        bars=[(WORLD, None)])
    assert WARP.run(args) == 6
    assert calls == []
    assert not dest.exists()


def test_a_box_row_that_lingers_gets_one_return_and_move_mode_is_left(
        monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(
        monkeypatch, tmp_path, arrival_choice="SNEAK IN",
        bars=[(YULASH, "press_bar"), (STORY, "press_kernal", 3),
              ("I,J,K,M, RETURN OR BUTTON", "leave_move"), (WORLD, None)])
    assert WARP.run(args) == 0
    assert calls == ["press_bar:SNEAK IN", "return", "leave_move",
                     "save_game", "walk_proof"]


def test_a_disk_still_open_after_the_save_is_attached_again_and_copied(
        monkeypatch, tmp_path):
    calls, args, dest = _run_with_fakes(monkeypatch, tmp_path)
    real = WARP.por.copy_closed_disk
    tries = []

    def copy(src, dst, **kw):
        tries.append(kw)
        if "attach" not in calls:
            raise RuntimeError("open directory entry 'SAVEAZURE'")
        return real(src, dst, **kw)

    monkeypatch.setattr(WARP.por, "copy_closed_disk", copy)
    assert WARP.run(args) == 0
    assert calls == ["save_game", "attach", "walk_proof"]
    assert len(tries) == 2
    saved = json.loads((tmp_path / "out" / "saved.json").read_text())
    assert saved["ok"] and saved["reattached"]
    assert dest.read_bytes() == disk_bytes(tmp_path)
