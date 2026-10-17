"""The Wish/FS-UAE acceptance runner, without an emulator, a window or game disks."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import pathlib
from types import SimpleNamespace

import pytest

from automap import amiga
from tools.amiga import fsuaewishaccept, winwishaccept

GAME_KEY = "secret-of-the-silver-blades"


def _args(tmp_path, **extra):
    values = {"title": "ssb", "holder": "test-fwa", "manifest": tmp_path / "prepare.json",
              "out": tmp_path, "deadline": 3300, "leg": "mapping", "discover": None}
    values.update(extra)
    return argparse.Namespace(**values)


def _phase(name, initial, *steps):
    return SimpleNamespace(name=name, initial_state=initial, steps=steps,
                           ready=True, reason=None, pages=())


def _step(kind, state, key=None, checkpoint=None, snapshot=None, encounters=None):
    return SimpleNamespace(kind=kind, state=state, key=key, checkpoint=checkpoint,
                           expected=None, drive=None, media=None, snapshot=snapshot,
                           encounters=encounters, relaunch=False, reads=())


def _route(*, title="ssb", load=None, reopen=None, media=(), mounted=()):
    phases = (_phase("load", "title", *(load or (_step("key", "world", key="L",
                                                         checkpoint="loaded"),))),
              _phase("stationary", "world"), _phase("walk", "world"),
              _phase("transition", "world"), _phase("reload", "world"),
              _phase("reopen_step", "world",
                     *(reopen or (_step("key", "world", key="V", checkpoint="reopened"),))))
    return SimpleNamespace(title=title, game_key=GAME_KEY,
                           amiga_title=SimpleNamespace(wait_limits={}, title_limit=30,
                                                       interstitials=(), options=(),
                                                       issue="1"),
                           phases=phases, actions=(), media=media, mounted=mounted,
                           unresolved=(), provenance={}, loaded_slot="B")


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.25
        return self.now


class FakeGame:
    """The `FsuaeGuest` calls the runner makes, recorded in order."""

    def __init__(self, tmp_path):
        self.calls = []
        self.slot = SimpleNamespace(port=6531, display=":93")
        self.work = tmp_path / "fsuae-test-fwa"
        self.work.mkdir()
        self.last_shot = None
        self.staged = {}

    @staticmethod
    def remote_path(issue, holder, key):
        return f"wish{issue}-{holder}-{key}.adf"

    def claim(self, holder, timeout):
        self.calls.append(("claim",))
        return "ok claimed"

    def put(self, local, remote, timeout):
        self.calls.append(("put", remote))
        self.staged[remote] = pathlib.Path(local).read_bytes()

    def start(self, holder, *drives, timeout, options=(), config=None, attach=True):
        self.calls.append(("start", drives, attach))
        (self.work / "environ.txt").write_text("SDL_AUDIODRIVER=dummy\nALSOFT_DRIVERS=null\n")
        return "ok pid=1"

    def silence(self, proof=None):
        return True

    def note_recognised(self):
        self.calls.append(("recognised",))

    def grab(self, state, raw, crop, timeout):
        pathlib.Path(raw).write_bytes(b"raw")
        pathlib.Path(crop).write_bytes(state.encode())
        self.last_shot = {"source": "fsuae-alt-s", "file": "x.png"}
        return True

    def press(self, holder, key, timeout):
        self.calls.append(("press", key))

    def snapshot(self, name, holder):
        self.calls.append(("snapshot", name))

    def restore(self, name, holder, fresh=False):
        self.calls.append(("restore", name))

    def stop(self, holder, timeout):
        self.calls.append(("stop",))
        return "ok stopped"

    def get(self, remote, local, timeout):
        self.calls.append(("get", remote))
        pathlib.Path(local).write_bytes(self.staged[remote])

    def release(self, holder, timeout):
        self.calls.append(("release",))
        return "ok released"


class FakeWish:
    """`fsuaegdb.WishRun`: the window opens and closes, and pumping moves the clock."""

    def __init__(self, clock, rows=None):
        self.clock = clock
        self.app = object()
        self.window = None
        self.events = []
        self.tab_log = []
        self.reads_per_pump = 1
        self.rows = rows or (lambda: [])

    def open(self):
        shown = []
        self.window = SimpleNamespace(tabs=SimpleNamespace(
            setCurrentIndex=lambda index: (self.tab_log.append(("tab", index)), shown.append(index)),
            currentIndex=lambda: shown[-1]), mapper=SimpleNamespace(_ticks=0))
        self.events.append("open")

    def close(self):
        self.window = None
        self.events.append("close")

    def pump(self, seconds):
        self.clock.now += seconds
        if self.window is not None:
            self.window.mapper._ticks += self.reads_per_pump

    def wait_connected(self, seconds):
        return {"connected": True, "seconds": 1.0, "helper": {"alive": True, "pid": 7}}

    def buttons(self):
        return self.rows()


class FakeTarget:
    layout = amiga.MACHINES[GAME_KEY]
    data_base = None
    memory = ()

    def __init__(self):
        self.closed = False

    def fix(self):
        return SimpleNamespace(x=3, y=3, facing=2, outdoors=False, world_map=False,
                               window=None, heading=None)

    def geo(self):
        return None

    def close(self):
        self.closed = True


class FakeGdb:
    lost = False
    sock = object()

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _controller(tmp_path, monkeypatch, *, route=None, guards=None, rows=None):
    clock, game = FakeClock(), FakeGame(tmp_path)
    wish = FakeWish(clock, rows)
    made = []

    def machine(port):
        made.append((FakeGdb(), FakeTarget(), amiga.MACHINES[GAME_KEY]))
        return made[-1]

    controller = fsuaewishaccept.FsuaeController(
        _args(tmp_path), game=game, guards=guards or (lambda state, crop: True),
        route=route or _route(), info={"media": {}}, wish_run=wish, machine=machine,
        clock=clock)
    monkeypatch.setattr(fsuaewishaccept.fsuaegdb, "helper_row",
                        lambda port: {"alive": False, "pid": None})
    monkeypatch.setattr(controller, "_enter_environment",
                        lambda: game.calls.append(("environment",)))
    monkeypatch.setattr(controller, "_leave_environment",
                        lambda: game.calls.append(("environment_restored",)))
    monkeypatch.setattr(controller, "_shoot_window", lambda path: path.write_bytes(b"png"))
    return controller, game, wish, made


def _no_winwish(monkeypatch):
    """Every function of the WinUAE window module raises if called."""
    def forbidden(name):
        def call(*args, **kwargs):
            raise AssertionError(f"winwish.{name} was called")
        return call
    for name, value in vars(winwishaccept.winwish).items():
        if inspect.isfunction(value):
            monkeypatch.setattr(winwishaccept.winwish, name, forbidden(name))


def test_a_route_runs_with_no_winwish_call_and_writes_its_rows(tmp_path, monkeypatch):
    _no_winwish(monkeypatch)
    # Pools of Darkness has no flag check, so the window opens and closes only for the reopen.
    controller, game, wish, made = _controller(tmp_path, monkeypatch, route=_route(title="darkness"))
    result = controller.run_title()

    assert result["failure"] is None, result["failure"]
    assert result["cleanup"]["errors"] == []
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert {name: summary["mapping"][name]["status"] for name in
            ("title", "load", "reopen", "disconnect")} == dict.fromkeys(
                ("title", "load", "reopen", "disconnect"), "awaiting image review")
    assert set(summary["checkpoints"]) == {"loaded", "reopened"}
    # Opened at the start and again for the checkpoint after the reopen; closed for the
    # reopen and at cleanup. The emulator stops for the disconnect grabs, once.
    assert wish.events == ["open", "close", "open", "close"]
    assert [call[0] for call in game.calls].count("stop") == 1
    assert [call for call in game.calls if call[0] == "press"] == [("press", "L"), ("press", "V")]
    assert all((tmp_path / f"disconnect-{n}.png").is_file() for n in range(3))
    assert [entry["at"] for entry in summary["helper_rows"]] == ["open", "close", "open", "close"]
    # One helper client served both checkpoints' reads, and nothing closed it until cleanup.
    assert len(made) == 1 and made[0][0].closed


def test_start_asks_for_no_debugger_of_its_own(tmp_path, monkeypatch):
    medium = tmp_path / "save.adf"
    medium.write_bytes(b"adf")
    route = _route(media=(SimpleNamespace(key="df0", path=medium, sha256="0" * 64),),
                   mounted=("df0",))
    controller, game, wish, _ = _controller(tmp_path, monkeypatch, route=route)
    controller.info["media"] = {"df0": {}}
    controller._up()

    start = next(call for call in game.calls if call[0] == "start")
    assert start == ("start", ("wish1-test-fwa-df0.adf",), False)
    assert [call[0] for call in game.calls][:4] == ["claim", "put", "start", "environment"]
    assert wish.events == ["open"]
    assert "SDL_AUDIODRIVER=dummy" in controller.summary["silence"]["environ"]


def test_the_map_tab_is_never_left_during_a_route(tmp_path, monkeypatch):
    controller, _game, wish, _ = _controller(tmp_path, monkeypatch, route=_route(title="darkness"))
    controller.run_title()

    # A tab switch resumes the mapper, which is not what a player who keeps the map showing sees.
    assert wish.tab_log == []
    assert "map_tab" not in {e["event"] for e in _events(tmp_path)}


def _events(tmp_path):
    return [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]


def test_each_key_waits_for_two_wish_reads(tmp_path, monkeypatch):
    controller, _game, wish, _ = _controller(tmp_path, monkeypatch, route=_route(title="darkness"))
    controller.run_title()

    wanted = ("key", "wish_reads", "wish_closed")
    events = [e for e in _events(tmp_path) if e["event"] in wanted]
    reads = [e for e in events if e["event"] == "wish_reads"]
    assert reads and all(e["reads"] >= 2 for e in reads)
    # While Wish is open, no key is followed by another key before Wish has read.
    for first, second in zip(events, events[1:]):
        if first["event"] == "key":
            assert second["event"] in ("wish_reads", "wish_closed")


def test_a_key_wish_never_reads_after_stops_the_run(tmp_path, monkeypatch):
    controller, _game, wish, _ = _controller(tmp_path, monkeypatch)
    wish.open()
    wish.reads_per_pump = 0
    with pytest.raises(winwishaccept.AcceptanceStop, match="Wish read the game"):
        controller._press("L")


def test_a_key_with_wish_closed_does_not_wait_for_reads(tmp_path, monkeypatch):
    controller, _game, wish, _ = _controller(tmp_path, monkeypatch)
    pumped = []
    monkeypatch.setattr(wish, "pump", lambda seconds: pumped.append(seconds))
    controller._let_wish_read("L")
    assert pumped == []


def _flag_rows(actions_on):
    names = ("Heal party", "Save spells", "Restore spells", "Identify", "Quickfight off")
    rows = [{"name": f"action_{n}", "text": name, "enabled": actions_on, "visible": True}
            for n, name in enumerate(names)]
    rows.append({"name": "ft_button", "text": "Fast &Travel", "enabled": True, "visible": True})
    rows.append({"name": "card_0_level_up", "text": "Level up", "enabled": actions_on,
                 "visible": True})
    return rows


def test_control_lines_pass_the_winuae_flag_check(tmp_path, monkeypatch):
    clock = FakeClock()
    controller = winwishaccept.Controller(
        _args(tmp_path), guest=object(), lane=object(), game=object(), guards=object(),
        route=_route(title="pool"), zipped=tmp_path / "build.zip", info={"media": {}},
        clock=clock, sleep=lambda seconds: None)
    monkeypatch.setattr(controller, "_map_section", lambda: None)
    monkeypatch.setattr(controller, "_game_section", lambda: None)
    readings = iter((True, False, True))
    monkeypatch.setattr(winwishaccept.winwish, "ui", lambda *args: fsuaewishaccept.control_lines(
        _flag_rows(next(readings))))
    monkeypatch.setattr(winwishaccept.winwish, "shot", lambda *args: None)
    monkeypatch.setattr(winwishaccept.winwish, "restart_wish", lambda *args, **kwargs: None)
    controller.flag_controls()
    assert [value["status"] for value in controller.summary["flags"].values()] == [
        "awaiting image review"] * 3


def test_the_runner_flag_check_reopens_the_window_with_the_flag_off_then_on(tmp_path, monkeypatch):
    monkeypatch.setenv(fsuaewishaccept.ACTIONS_FLAG, "1")
    controller, _game, wish, _ = _controller(
        tmp_path, monkeypatch, route=_route(title="pool"),
        rows=lambda: _flag_rows(os.environ.get(fsuaewishaccept.ACTIONS_FLAG) == "1"))
    wish.open()
    controller.flag_controls()
    assert wish.events == ["open", "close", "open", "close", "open"]
    assert [value["status"] for value in controller.summary["flags"].values()] == [
        "awaiting image review"] * 3
    assert os.environ[fsuaewishaccept.ACTIONS_FLAG] == "1"


def test_the_runner_flag_check_stops_when_map_only_leaves_an_action_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv(fsuaewishaccept.ACTIONS_FLAG, "1")
    controller, _game, wish, _ = _controller(tmp_path, monkeypatch, route=_route(title="pool"),
                                             rows=lambda: _flag_rows(True))
    wish.open()
    with pytest.raises(winwishaccept.AcceptanceStop, match="map-only flag left an action enabled"):
        controller.flag_controls()


def _ssb_media(tmp_path):
    disk = tmp_path / "disk.adf"
    disk.write_bytes(b"adf")
    return (SimpleNamespace(key="df0", path=disk, sha256=hashlib.sha256(b"adf").hexdigest()),), ("df0",)


@pytest.mark.parametrize("answered", [True, False])
def test_the_journal_step_answers_through_fsuaegdb(tmp_path, monkeypatch, answered):
    media, mounted = _ssb_media(tmp_path)
    controller, _game, _wish, _ = _controller(tmp_path, monkeypatch,
                                              route=_route(media=media, mounted=mounted))
    seen = []
    monkeypatch.setattr(fsuaewishaccept.fsuaegdb, "journal",
                        lambda args, adf="", guest=None:
                        seen.append((args.display, adf, guest is _game)) or answered)
    if answered:
        controller._answer_journal()
    else:
        with pytest.raises(winwishaccept.AcceptanceStop, match="journal was not answered"):
            controller._answer_journal()
    assert seen == [(":93", str(media[0].path), True)]


def test_the_journal_step_answers_the_question_on_the_guests_own_frame(tmp_path, monkeypatch):
    """The FS-UAE run's own journal screen is read and answered from the guest's Alt+S frame.

    The frame is specimen `WISH-SPEC-ssb-fsuae-journal-frame`, FS-UAE's own
    screenshot of the question in an `fsuaewishaccept` run that stopped there
    with no challenge read; the tables come off the player's Silver Blades
    disk and the reader out of the private repository.  Nothing about the
    question or the word is asserted in a form a failure would print.
    """
    from tests import gamedata
    from tools.amiga import amigabladesjournal as tool

    frame = gamedata.specimen("ssb-fsuae-journal-frame", "amiga") / "game-049.raw.png"
    try:
        tool._blades_modules()
        disk = tool.find_disk(None)
    except SystemExit as exc:
        pytest.skip(f"needs the private journal reader and a Silver Blades disk: {exc}")
    media = (SimpleNamespace(key="df0", path=disk, sha256=""),)
    controller, game, wish, _ = _controller(tmp_path, monkeypatch,
                                            route=_route(media=media, mounted=("df0",)))
    wish.open()
    game.shot = lambda path, timeout=30.0: pathlib.Path(path).write_bytes(frame.read_bytes())
    keys = []
    monkeypatch.setattr(fsuaewishaccept.fsuaegdb, "press",
                        lambda display, key, settle: keys.append(key))

    def root_grab(display, path):
        raise AssertionError("the X root grab was taken")

    monkeypatch.setattr(fsuaewishaccept.fsuaegdb, "shot", root_grab)
    controller._answer_journal()
    typed_a_word_then_return = len(keys) > 1 and keys[-1] == "Return"
    assert typed_a_word_then_return
    assert controller.summary["interstitial_keys"] == 1
    assert _events(tmp_path)[-1]["event"] == "wish_reads"


def test_the_code_wheel_stops_the_run_naming_the_screen(tmp_path, monkeypatch):
    controller, *_ = _controller(tmp_path, monkeypatch)
    with pytest.raises(winwishaccept.AcceptanceStop, match="curse_wheel"):
        controller._answer_wheel("curse_wheel")


def test_the_snapshot_step_switches_encounters_off_first(tmp_path, monkeypatch):
    route = _route(load=(_step("key", "world", key="L"),
                         _step("snapshot", "world", snapshot="walk")))
    controller, game, _wish, _ = _controller(tmp_path, monkeypatch, route=route)
    switch = SimpleNamespace(on=lambda: {}, off=lambda: game.calls.append(("off",)) or {},
                             keys=lambda names: game.calls.append(("press", *names)) or {
                                 "pressed": names},
                             state=SimpleNamespace(load=lambda: {"on": False, "rows": []}),
                             enc=SimpleNamespace(active=False), reapply=lambda: None)
    controller.encounters, controller.encounters_on = switch, True
    controller.run_phase(route.phases[0])
    order = [call[0] for call in game.calls if call[0] in ("off", "snapshot")]
    assert order == ["off", "snapshot"]
    assert controller.encounters_on is False


def test_the_encounter_switch_waits_for_wish_to_read(tmp_path, monkeypatch):
    controller, _game, wish, _ = _controller(tmp_path, monkeypatch)
    wish.open()
    controller.encounters = SimpleNamespace(
        on=lambda: {}, off=lambda: {},
        state=SimpleNamespace(load=lambda: {"on": False, "rows": []}))
    controller._switch(False)
    assert _events(tmp_path)[-1]["event"] == "wish_reads"


@pytest.mark.parametrize("extra, message", [
    ({"discover": "ssb-leave"}, "discovery modes"),
    ({"leg": "persist"}, "--leg persist"),
    ({"leg": "reconnect"}, "--leg reconnect"),
])
def test_the_modes_left_out_stop_before_the_claim(tmp_path, extra, message):
    game = SimpleNamespace(claim=lambda *a: pytest.fail("claimed"))
    with pytest.raises(winwishaccept.AcceptanceStop, match=message):
        fsuaewishaccept.preflight(_args(tmp_path, **extra), game=game,
                                  route_for=lambda *a: pytest.fail("route read"))


def test_a_guest_that_cannot_start_unattached_stops_before_the_claim(tmp_path):
    (tmp_path / "prepare.json").write_text("{}")

    class OldGuest:
        last_shot = None

        def start(self, holder, *drives, timeout, options=(), config=None):
            raise AssertionError("started")

        def claim(self, *args):
            raise AssertionError("claimed")

    with pytest.raises(winwishaccept.AcceptanceStop, match="without attaching"):
        fsuaewishaccept.preflight(_args(tmp_path), game=OldGuest(),
                                  route_for=lambda title, manifest: _route())


def test_a_reset_route_stops_before_the_claim_on_a_guest_with_no_reset(tmp_path):
    (tmp_path / "prepare.json").write_text("{}")
    route = _route(reopen=(_step("reset", "title"), _step("key", "world", key="V")))
    game = FakeGame(tmp_path)
    with pytest.raises(winwishaccept.AcceptanceStop, match="reset step"):
        fsuaewishaccept.preflight(_args(tmp_path), game=game,
                                  route_for=lambda title, manifest: route)
    assert game.calls == []


def test_a_snapshot_route_stops_before_the_claim_on_a_guest_whose_snapshot_is_a_placeholder(tmp_path):
    (tmp_path / "prepare.json").write_text("{}")
    route = _route(reopen=(_step("snapshot", "world", snapshot="walk"), _step("key", "world", key="V")))

    class StubbedGame(FakeGame):
        def supports(self, kind):
            return kind != "snapshot"

    game = StubbedGame(tmp_path)
    with pytest.raises(winwishaccept.AcceptanceStop, match="snapshot is not built yet"):
        fsuaewishaccept.preflight(_args(tmp_path), game=game,
                                  route_for=lambda title, manifest: route)
    assert game.calls == []


def test_the_fs_uae_guest_passes_the_preflight_for_its_state_and_reset_steps(tmp_path):
    from tools.amiga import fsuaesession

    route = _route(reopen=(_step("snapshot", "world", snapshot="walk"), _step("restore", "world", snapshot="walk"),
                           _step("reset", "title"), _step("key", "world", key="V")))
    assert fsuaewishaccept.guest_gaps(fsuaesession.FsuaeGuest(), route) == []


def test_cleanup_still_stops_copies_and_releases_after_a_failure(tmp_path, monkeypatch):
    media, mounted = _ssb_media(tmp_path)
    controller, game, wish, _ = _controller(tmp_path, monkeypatch,
                                            route=_route(media=media, mounted=mounted))
    controller.info["media"] = {"df0": {}}

    def broken(state, raw, crop, timeout):
        raise winwishaccept.RouteError("FS-UAE wrote no screenshot")

    monkeypatch.setattr(game, "grab", broken)
    result = controller.run_title()

    assert "FS-UAE wrote no screenshot" in result["failure"]
    names = [call[0] for call in game.calls]
    assert names.index("stop") < names.index("get") < names.index("release")
    assert names[-1] == "environment_restored"
    assert wish.events == ["open", "close"]
    assert (tmp_path / "working-df0.adf").read_bytes() == b"adf"
    assert json.loads((tmp_path / "summary.json").read_text())["failure"] == result["failure"]


def test_a_claim_whose_log_line_cannot_be_written_still_releases_the_slot(tmp_path, monkeypatch):
    controller, game, _wish, _ = _controller(tmp_path, monkeypatch)
    real_log = controller.log

    def log(event, **payload):
        if event == "claim":
            raise OSError("disk full")
        return real_log(event, **payload)

    monkeypatch.setattr(controller, "log", log)
    result = controller.run_title()
    assert "disk full" in result["failure"]
    assert [call[0] for call in game.calls].count("release") == 1


def test_reads_reuse_one_helper_client_until_the_program_restarts(tmp_path, monkeypatch):
    controller, _game, _wish, made = _controller(tmp_path, monkeypatch)
    lap = lambda part: None  # noqa: E731
    first, _ = controller._read_engine(lap)
    controller._read_engine(lap)
    assert first["fix"]["x"] == 3
    assert len(made) == 1 and not made[0][0].closed and not made[0][1].closed
    controller._relaunched()
    controller._read_engine(lap)
    assert made[0][0].closed and len(made) == 2


class FakeEncounters:
    """`fsuaegdb.Encounters` as far as the adapter calls it."""

    def __init__(self, note, *, blocks=False):
        self.note, self.blocks = note, blocks
        self.active, self.title, self.rows = False, GAME_KEY, []

    def command(self, rest, now):
        self.active = rest == "on"

    def outstanding(self):
        return self.rows

    def blocks_key(self, key, now):
        return self.blocks

    def reapply(self, now):
        pass

    def close(self):
        pass


def _adapter(blocks=False, title=GAME_KEY):
    pressed = []
    holder = {}

    def build(note):
        holder["enc"] = FakeEncounters(note, blocks=blocks)
        holder["enc"].title = title
        return holder["enc"]

    adapter = fsuaewishaccept._Encounters(GAME_KEY, None, 6531, log=lambda *a, **k: None,
                                          press=pressed.append, now=lambda: 0.0,
                                          encounters=build(lambda **row: adapter._note(**row)))
    return adapter, pressed


def test_the_encounter_adapter_reports_on_off_and_its_rows():
    adapter, pressed = _adapter()
    assert adapter.on() == {"on": True}
    assert adapter.state.load() == {"on": True, "rows": []}
    assert adapter.keys(["NP8"]) == {"pressed": ["NP8"]} and pressed == ["NP8"]
    assert adapter.off() == {"on": False}
    assert adapter.state.load() == {"on": False, "rows": []}


def test_the_encounter_adapter_stops_a_blocked_key_and_another_title():
    adapter, pressed = _adapter(blocks=True)
    assert "stopped" in adapter.keys(["S"]) and pressed == []
    other, _ = _adapter(title="pool-of-radiance")
    assert "pool-of-radiance" in other.on()["error"]


def _controller_log(events):
    """The WinUAE Controller.log signature, with `event` as its first parameter."""
    def log(event, **data):
        events.append({"event": event, **data})
    return log


def test_the_encounter_switch_notes_reach_the_controller_log():
    events = []
    fake = FakeEncounters(None)
    adapter = fsuaewishaccept._Encounters(
        GAME_KEY, None, 6531, log=_controller_log(events), press=lambda key: None,
        now=lambda: 0.0, encounters=fake)
    fake.note = lambda **row: adapter._note(**row)
    adapter.on()
    fake.note(event="no_encounters", action="on", at=0.0)
    adapter.off()
    fake.note(event="no_encounters", action="off", at=0.0)
    rows = [e for e in events if e["event"] == "no_encounters_row"]
    assert [row["action"] for row in rows] == ["on", "off"]
    assert all(row["note_event"] == "no_encounters" for row in rows)


def test_an_interrupt_note_reaches_the_controller_log():
    events = []
    log = _controller_log(events)
    fsuaewishaccept._log_note(log, "interrupt", {"event": "crash", "error": "stop"})
    assert events == [{"event": "interrupt", "note_event": "crash", "error": "stop"}]
