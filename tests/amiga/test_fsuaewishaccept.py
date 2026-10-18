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
    monkeypatch.setattr(controller, "_controls_listing",
                        lambda: fsuaewishaccept.control_lines(wish.buttons()))
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
    ({"quickfight_control": True}, "--quickfight-control"),
    ({"leg": "fight", "watch": True, "watch_dip": True}, "--watch-dip"),
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


def _hold_route(seconds=120.0, **step_fields):
    from tools.amiga import maproute

    hold = maproute.Phase("stationary", "world", (
        maproute.Step("key", "question", key="E"),
        maproute.Step("hold", "question", seconds=seconds, **step_fields),
        maproute.Step("key", "world", key="S")))
    route = _route(title="darkness")
    route.phases = tuple(hold if phase.name == "stationary" else phase for phase in route.phases)
    return route


def test_a_hold_step_waits_on_its_screen_with_no_key_and_wish_polling(tmp_path, monkeypatch):
    controller, game, wish, _ = _controller(tmp_path, monkeypatch, route=_hold_route())
    pumped = []
    pump = wish.pump
    wish.pump = lambda seconds: (pumped.append((round(wish.clock.now, 2), seconds)), pump(seconds))
    pressed_at = []
    press = game.press
    game.press = lambda holder, key, timeout: (pressed_at.append((key, wish.clock.now)),
                                               press(holder, key, timeout))
    result = controller.run_title()

    assert result["failure"] is None, result["failure"]
    keys = dict((key, at) for key, at in pressed_at if key in ("E", "S"))
    assert keys["S"] - keys["E"] >= 120
    assert [entry["held"] >= 120 for entry in result["holds"]] == [True]
    assert result["holds"][0]["state"] == "question"
    assert max(seconds for _at, seconds in pumped) >= 119
    assert result["completed_sequence"].count("stationary") == 1
    events = [json.loads(line)["event"] for line in (tmp_path / "events.jsonl").open()]
    assert events.index("hold") < events.index("hold_end")


def test_a_hold_cut_short_by_the_route_time_stops_the_run(tmp_path, monkeypatch):
    controller, *_ = _controller(tmp_path, monkeypatch, route=_hold_route(seconds=3000))
    result = controller.run_title()
    assert "hold on question ended after" in result["failure"]


@pytest.mark.parametrize("step,message", [
    ({"seconds": None}, "positive number of seconds"),
    ({"seconds": 5, "checkpoint": "held"}, "no checkpoint"),
    ({"seconds": 5, "state": "world"}, "follows a step that reached question"),
])
def test_a_hold_step_without_a_key_must_wait_on_the_screen_before_it(step, message):
    from tools.amiga import maproute

    fields = {"seconds": None, "checkpoint": None, "state": "question", **step}
    route = _route()
    route.phases = (maproute.Phase("outdoor", "world", (
        maproute.Step("key", "question", key="E"),
        maproute.Step("hold", fields["state"], seconds=fields["seconds"],
                      checkpoint=fields["checkpoint"]))),)
    with pytest.raises(winwishaccept.AcceptanceStop, match=message):
        fsuaewishaccept.check_holds(route)


def test_a_hold_with_a_key_presses_it_then_waits_with_no_grab(tmp_path, monkeypatch):
    from tools.amiga import maproute

    route = _hold_route()
    route.phases = tuple(maproute.Phase("stationary", "world", (
        maproute.Step("key", "question", key="E"),
        maproute.Step("hold", "world", key="S", seconds=60.0))) if phase.name == "stationary"
        else phase for phase in route.phases)
    fsuaewishaccept.check_holds(route)
    controller, game, wish, _ = _controller(tmp_path, monkeypatch, route=route)
    grabs, pressed = [], []
    grab, press = game.grab, game.press
    game.grab = lambda state, raw, crop, timeout: (grabs.append(wish.clock.now),
                                                   grab(state, raw, crop, timeout))[1]
    game.press = lambda holder, key, timeout: (pressed.append((key, wish.clock.now)),
                                               press(holder, key, timeout))
    result = controller.run_title()

    assert result["failure"] is None, result["failure"]
    at = dict(pressed)["S"]
    later = [when for when in grabs if when > at]
    assert later and min(later) - at >= 60
    assert result["holds"][0]["held"] >= 60


def test_the_arrival_hold_leg_passes_the_hold_check(tmp_path):
    from tools.amiga import maproute

    manifest = {"title": "curse", "loaded_letter": "B",
                "disks": {key: {"path": str(tmp_path / f"{key}.adf"), "sha256": "a" * 64}
                          for key in ("save", "diskb")},
                "substitute": {"letter": "C", "sha256": maproute._CURSE_YULASH_SHA256},
                "state_a": {"area": 16, "x": 2, "y": 6, "facing": 1}}
    fsuaewishaccept.check_holds(maproute.route_for("curse", manifest, arrival_hold=120))


def test_preflight_passes_the_measurement_legs_to_the_route_and_only_for_curse(tmp_path):
    seen = []

    def route_for(title, manifest, **legs):
        seen.append(legs)
        raise winwishaccept.RouteError("stop here")

    (tmp_path / "prepare.json").write_text(json.dumps({"title": "curse"}))
    game = FakeGame(tmp_path)
    args = _args(tmp_path, title="curse", arrival_hold=120.0, search_area=False)
    with pytest.raises(winwishaccept.AcceptanceStop, match="stop here"):
        fsuaewishaccept.preflight(args, game=game, route_for=route_for)
    assert seen == [{"arrival_hold": 120.0}]
    with pytest.raises(winwishaccept.AcceptanceStop, match="Curse legs"):
        fsuaewishaccept.preflight(_args(tmp_path, title="ssb", arrival_hold=120.0),
                                  game=game, route_for=route_for)


def _curse_save_manifest(tmp_path):
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

    disk = AmigaDisk.blank("Save")
    disk.make_dir("/SAVE")
    disk.write_file(amiga_savegame.slot_path(amiga_savegame.CURSE, "B"), bytes(6000))
    save = tmp_path / "source" / "save.adf"
    save.parent.mkdir()
    disk.save(save)
    manifest = tmp_path / "source" / "prepare.json"
    manifest.write_text(json.dumps({
        "title": "curse", "loaded_letter": "B",
        "disks": {"save": {"path": str(save), "sha256": winwishaccept.digest(save)},
                  "diskb": {"path": "/b.adf", "sha256": "b" * 64}}}))
    return manifest, save


def test_search_area_staging_sets_the_flag_on_a_copy_and_names_the_copy(tmp_path):
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import maproute

    manifest, save = _curse_save_manifest(tmp_path)
    before = winwishaccept.digest(save)
    staged = fsuaewishaccept.stage_search_area(manifest, tmp_path / "run" / "staged-search")

    written = json.loads(staged.read_text())
    copy = pathlib.Path(written["disks"]["save"]["path"])
    assert copy.parent == tmp_path / "run" / "staged-search"
    assert written["disks"]["save"]["sha256"] == winwishaccept.digest(copy) != before
    assert winwishaccept.digest(save) == before
    data = AmigaDisk.open(copy).read_file(amiga_savegame.slot_path(amiga_savegame.CURSE, "B"))
    assert amiga_savegame.word(data, 0x4A5B, amiga_savegame.CURSE) == 1
    assert {k: written["staged_word"][k] for k in ("word", "before", "after")} == {
        "word": "$4C5B", "before": 0, "after": 1}
    media = (maproute.Media("save", copy, written["disks"]["save"]["sha256"]),)
    assert maproute.search_flag(media, "B") == 1
    with pytest.raises(winwishaccept.AcceptanceStop, match="already exists"):
        fsuaewishaccept.stage_search_area(manifest, tmp_path / "run" / "staged-search")


class _PollTarget:
    def __init__(self, geo):
        self.geo_bytes = geo

    def resident_geo_address(self):
        return 0x20000

    def read(self, address, length):
        assert (address, length) == (0x20000, 0x400)
        return self.geo_bytes


def test_the_poll_log_records_each_polls_own_fix_and_the_resident_map(tmp_path, monkeypatch):
    from automap import state
    from goldbox.geo import Geo

    block = bytes(range(256)) * 4
    fix = SimpleNamespace(x=0, y=8, facing=3, source="memory", world_map=False,
                          world_node=None, outdoors=False)
    reads = []

    def read_fix(target, game=None):
        reads.append(target)
        return fix

    def poll(mapper):
        state.read_fix(mapper.target, None)
        return True

    monkeypatch.setattr(state, "read_fix", read_fix)
    monkeypatch.setattr(state.Automapper, "poll", poll)
    mapper = SimpleNamespace(
        target=_PollTarget(block), _maps={"GEO10": Geo(block), "GEO11": Geo(bytes(1024))},
        state=SimpleNamespace(x=2, y=6, facing=1, area="GEO10", world_map=False, outdoors=False),
        _pending=(0, 8), _verdict="ours")
    log = fsuaewishaccept.PollLog(tmp_path / "polls.jsonl", lambda: 12.5)
    log.install()
    try:
        assert state.Automapper.poll(mapper) is True
    finally:
        log.remove()

    assert state.Automapper.poll is poll and state.read_fix is read_fix
    row = json.loads((tmp_path / "polls.jsonl").read_text())
    assert reads == [mapper.target]
    assert row["poll"] == 1 and row["elapsed"] == 12.5 and row["changed"] is True
    assert row["fix"] == {"x": 0, "y": 8, "facing": 3, "source": "memory", "world_map": False,
                          "world_node": None, "outdoors": False}
    assert (row["geo_address"], row["geo_name"]) == ("0x20000", "GEO10")
    assert row["believed"]["x"] == 2 and row["pending"] == [0, 8] and row["verdict"] == "ours"


def test_a_poll_log_row_keeps_the_error_and_the_poll_goes_on(tmp_path, monkeypatch):
    from automap import state

    monkeypatch.setattr(state.Automapper, "poll", lambda mapper: False)
    broken = SimpleNamespace(resident_geo_address=lambda: (_ for _ in ()).throw(OSError("gone")))
    log = fsuaewishaccept.PollLog(tmp_path / "polls.jsonl", lambda: 1.0)
    log.install()
    try:
        assert state.Automapper.poll(SimpleNamespace(target=broken)) is False
    finally:
        log.remove()
    row = json.loads((tmp_path / "polls.jsonl").read_text())
    assert row["error"] == "OSError: gone" and row["fix"] is None


def test_a_poll_log_write_failure_is_kept_and_logging_stops(tmp_path, monkeypatch):
    from automap import state

    monkeypatch.setattr(state.Automapper, "poll", lambda mapper: True)
    log = fsuaewishaccept.PollLog(tmp_path / "missing" / "polls.jsonl", lambda: 1.0)
    log.install()
    try:
        assert state.Automapper.poll(SimpleNamespace(target=SimpleNamespace())) is True
        assert state.Automapper.poll(SimpleNamespace(target=SimpleNamespace())) is True
    finally:
        log.remove()
    assert log.polls == 2 and log.failure.startswith("FileNotFoundError")


def test_an_arrival_hold_of_zero_reaches_the_route_check(tmp_path):
    seen = []

    def route_for(title, manifest, **legs):
        seen.append(legs)
        raise winwishaccept.RouteError("stop here")

    (tmp_path / "prepare.json").write_text(json.dumps({"title": "curse"}))
    with pytest.raises(winwishaccept.AcceptanceStop):
        fsuaewishaccept.preflight(_args(tmp_path, title="curse", arrival_hold=0.0,
                                        search_area=False),
                                  game=FakeGame(tmp_path), route_for=route_for)
    assert seen == [{"arrival_hold": 0.0}]


def test_the_measurement_options_turn_the_poll_log_on(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(fsuaewishaccept, "preflight",
                        lambda args, **kwargs: seen.append(args) or (_ for _ in ()).throw(
                            winwishaccept.AcceptanceStop("stop")))
    common = ["--title", "curse", "--manifest", str(tmp_path / "m.json"), "--holder", "h",
              "--out", str(tmp_path)]
    for extra in (["--arrival-hold", "120"], ["--search-area"], ["--poll-log"], []):
        assert fsuaewishaccept.main(common + extra) == 2
    assert [args.poll_log for args in seen] == [True, True, True, False]
    assert seen[0].arrival_hold == 120.0 and seen[1].search_area is True


def test_idle_loads_the_party_then_sends_no_key_and_no_grab_and_ends_the_run(tmp_path, monkeypatch):
    from automap import state

    controller, game, wish, _ = _controller(tmp_path, monkeypatch, route=_route(title="darkness"))
    controller.args.idle, controller.args.poll_log = 30.0, True
    durations = iter((1.0, 6.0, 2.0, 1.0, 1.0, 1.0, 1.0))
    mapper = SimpleNamespace(target=SimpleNamespace(), state=SimpleNamespace(), _maps={})

    def poll(_mapper):
        wish.clock.now += next(durations)
        return False

    monkeypatch.setattr(state.Automapper, "poll", poll)
    pump = wish.pump
    idling = []

    def pumping(seconds):
        if seconds >= 20:
            idling.append(seconds)
            for _ in range(5):
                state.Automapper.poll(mapper)
                wish.clock.now += 3.0
        pump(seconds)

    wish.pump = pumping
    grabbed, pressed = [], []
    grab, press = game.grab, game.press
    game.grab = lambda state_name, raw, crop, timeout: (grabbed.append(wish.clock.now),
                                                        grab(state_name, raw, crop, timeout))[1]
    game.press = lambda holder, key, timeout: (pressed.append(key), press(holder, key, timeout))
    pumped_at = []
    inner = wish.pump
    wish.pump = lambda seconds: (pumped_at.append(wish.clock.now) if seconds >= 20 else None,
                                 inner(seconds))
    result = controller.run_title()

    assert result["failure"] is None, result["failure"]
    assert idling, "Wish was never pumped for the idle"
    assert pressed == ["L"]
    assert not [at for at in grabbed if at > pumped_at[0]]
    idle = result["idle"]
    assert idle["seconds"] == 30.0 and idle["held"] >= 30 and idle["polls"] == 5
    assert 6 <= idle["longest_poll"] < 7
    assert 9 <= idle["longest_gap"] < 10
    assert result["poll_count"] == 5
    rows = [json.loads(line) for line in (tmp_path / fsuaewishaccept.POLL_LOG).open()]
    assert [r["poll"] for r in rows] == [1, 2, 3, 4, 5]
    assert all("started" in r and "duration" in r for r in rows)
    assert 6 <= rows[1]["duration"] < 7
    assert not (tmp_path / "connected.png").exists()
    assert result["completed_sequence"] == ["load"]
    assert ("stop",) in game.calls


@pytest.mark.parametrize("seconds", [0.0, -5.0])
def test_idle_needs_a_positive_number_of_seconds(tmp_path, seconds):
    (tmp_path / "prepare.json").write_text(json.dumps({"title": "darkness"}))

    def route_for(title, manifest, **legs):
        raise AssertionError("the route was built")

    with pytest.raises(winwishaccept.AcceptanceStop, match="--idle needs a positive"):
        fsuaewishaccept.preflight(_args(tmp_path, title="darkness", idle=seconds),
                                  game=FakeGame(tmp_path), route_for=route_for)


def test_idle_is_not_combined_with_a_curse_measurement_leg(tmp_path):
    (tmp_path / "prepare.json").write_text(json.dumps({"title": "curse"}))
    with pytest.raises(winwishaccept.AcceptanceStop, match="its own leg"):
        fsuaewishaccept.preflight(_args(tmp_path, title="curse", idle=30.0, arrival_hold=60.0),
                                  game=FakeGame(tmp_path), route_for=lambda *a, **k: None)


def test_idle_turns_the_poll_log_on(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(fsuaewishaccept, "preflight",
                        lambda args, **kwargs: seen.append(args) or (_ for _ in ()).throw(
                            winwishaccept.AcceptanceStop("stop")))
    common = ["--title", "darkness", "--manifest", str(tmp_path / "m.json"), "--holder", "h",
              "--out", str(tmp_path)]
    assert fsuaewishaccept.main(common + ["--idle", "300"]) == 2
    assert seen[0].idle == 300.0 and seen[0].poll_log is True


# -- the persist leg: Wish's controls, clicks and log --------------------------------------


def _persist_preflight(tmp_path, monkeypatch, **extra):
    media, mounted = _ssb_media(tmp_path)
    (tmp_path / "prepare.json").write_text("{}")
    route = _route(media=media, mounted=mounted)
    states = {"title", "world"}
    seen = []
    monkeypatch.setattr(winwishaccept, "leg_preflight", lambda args, route, manifest: {
        "persist": {"letter": "C", "actions": ["heal"]}, "plan": None, "specimen": None,
        "stage": None, "states": states})

    def export(args, route, wanted=None):
        seen.append(wanted)
        return "guards", {"export": "x"}

    binary = tmp_path / "fs-uae"
    binary.write_bytes(b"emulator")
    result = fsuaewishaccept.preflight(
        _args(tmp_path, leg="persist", action=["heal"], **extra), game=FakeGame(tmp_path),
        route_for=lambda title, manifest, **legs: route, binary=lambda: binary,
        kickstart=lambda: binary, driver=lambda: {"sha": "x", "dirty": False}, export=export,
        journal_check=lambda executable: None)
    return result, seen, states


def test_the_persist_leg_passes_preflight_with_its_plan_and_its_own_guard_states(tmp_path, monkeypatch):
    (_route_, guards, info), seen, states = _persist_preflight(tmp_path, monkeypatch)
    assert info["leg"] == "persist" and info["persist"]["letter"] == "C"
    assert seen == [states] and guards == "guards"


def test_the_mapping_leg_exports_its_guards_with_no_state_set(tmp_path, monkeypatch):
    media, mounted = _ssb_media(tmp_path)
    (tmp_path / "prepare.json").write_text("{}")
    seen = []
    binary = tmp_path / "fs-uae"
    binary.write_bytes(b"emulator")
    monkeypatch.setattr(winwishaccept, "_phase_map", lambda route: None)
    _r, _g, info = fsuaewishaccept.preflight(
        _args(tmp_path), game=FakeGame(tmp_path),
        route_for=lambda title, manifest, **legs: _route(media=media, mounted=mounted),
        binary=lambda: binary, kickstart=lambda: binary,
        driver=lambda: {"sha": "x", "dirty": False},
        export=lambda *a: (seen.append(a), ("g", {}))[1],
        journal_check=lambda executable: None)
    assert len(seen[0]) == 2 and "persist" not in info
    assert info["driver_sha"] == "x" and info["driver"] == {"sha": "x", "dirty": False}


def test_the_cleanup_records_the_working_disks_under_the_names_the_readers_use(tmp_path, monkeypatch):
    media, mounted = _ssb_media(tmp_path)
    controller, _game, _wish, _ = _controller(tmp_path, monkeypatch,
                                              route=_route(media=media, mounted=mounted))
    controller.info["media"] = {"df0": {}}
    controller.run_title()
    entry = controller.info["media"]["df0"]
    assert entry["guest_working_copy"] == str(tmp_path / "working-df0.adf")
    assert entry["guest_working_sha256"] == hashlib.sha256(b"adf").hexdigest()
    assert "working_copy" not in entry


def test_the_persist_leg_runs_inside_the_helper_reads(tmp_path, monkeypatch):
    from tools.amiga import amigatarget

    controller, _game, _wish, _ = _controller(tmp_path, monkeypatch)
    controller.leg = "persist"
    seen = []
    monkeypatch.setattr(controller, "run_persist",
                        lambda: seen.append(amigatarget.connect_pipe) or {"ok": True})
    assert controller.run_title() == {"ok": True}
    assert seen[0] == controller._connect


def test_a_greyed_click_raises_control_greyed_naming_the_label_clicked(tmp_path, monkeypatch):
    from tools.gui import windowbuttons

    controller, _game, wish, _ = _controller(tmp_path, monkeypatch)
    wish.window = SimpleNamespace(map=object())
    monkeypatch.setattr(windowbuttons, "rows", lambda window: [
        {"name": "action_heal", "text": "Heal party"}, {"name": "ft", "text": "Fast &Travel"}])
    calls = []

    def click(window, name, answer=None, spell=None, deadline=0):
        calls.append((name, answer))
        return {"error": "button is disabled" if name == "action_heal" else None, "dialogs": []}

    monkeypatch.setattr(windowbuttons, "click", click)
    with pytest.raises(winwishaccept.ControlGreyed) as raised:
        controller._click("Heal party")
    assert raised.value.control == "Heal party" and calls == [("action_heal", "yes")]
    with pytest.raises(winwishaccept.ControlGreyed) as by_id:
        controller._click(automation_id="x.action_heal")
    assert by_id.value.control == "action_heal"
    assert controller._click(automation_id="x.ft") == {"error": None, "dialogs": []}
    assert calls[-1] == ("ft", "yes")
    monkeypatch.setattr(windowbuttons, "click", lambda *a, **k: {"error": "button is hidden"})
    with pytest.raises(winwishaccept.AcceptanceStop, match="hidden"):
        controller._click("Heal party")
    with pytest.raises(winwishaccept.AcceptanceStop, match="0 buttons"):
        controller._click("Nothing")


def test_the_wish_log_blocks_read_the_session_log_and_the_crash_file(tmp_path):
    (tmp_path / "wish-20260101-000000.log").write_text(
        "10:00:00 INFO fine\n10:00:01 ERROR unhandled exception\nTraceback (most recent call last):\n"
        "  File \"x.py\", line 1, in f\nValueError: bad\n10:00:02 INFO after\n\n")
    (tmp_path / "crashes.log").write_text(
        "\n2026-01-01 10:00:05 versions\nTraceback (most recent call last):\n  File \"y\"\nKeyError: 'k'\n")
    (tmp_path / "other.txt").write_text("10:00:00 ERROR no\n")
    blocks = fsuaewishaccept.wish_log_blocks(tmp_path)
    assert [(b["file"], b["exception"]) for b in blocks] == [
        ("crashes.log", "KeyError: 'k'"), ("wish-20260101-000000.log", "ValueError: bad")]
    assert fsuaewishaccept.wish_log_blocks(tmp_path / "missing") == []


_SLOT_SCRIPT = """
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_CONFIG_HOME"] = sys.argv[1]
from PyQt6.QtWidgets import QApplication, QPushButton
from tools.amiga import fsuaewishaccept
from wish import debuglog
original = sys.excepthook
if sys.argv[2] == "hook":
    saved = fsuaewishaccept.install_wish_hooks()
app = QApplication([])
button = QPushButton()
def boom(_checked=False):
    raise RuntimeError("slot failed")
button.clicked.connect(boom)
button.click()
blocks = fsuaewishaccept.wish_log_blocks(debuglog.log_dir())
if sys.argv[2] == "hook":
    fsuaewishaccept.restore_wish_hooks(saved)
print(json.dumps({"exceptions": [b["exception"] for b in blocks],
                  "restored": sys.excepthook is original}))
"""


def test_an_exception_in_a_slot_of_the_in_process_window_reaches_wish_log(tmp_path):
    """Qt aborts the process on a slot exception unless the hook is installed, so this runs apart."""
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parents[2]
    done = subprocess.run([sys.executable, "-c", _SLOT_SCRIPT, str(tmp_path), "hook"], cwd=root,
                          env={**os.environ, "PYTHONPATH": str(root)}, text=True,
                          capture_output=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.splitlines()[-1]) == {
        "exceptions": ["RuntimeError: slot failed"], "restored": True}


@pytest.mark.parametrize("extra, message", [
    ({"action": ["heal"]}, "--action needs --leg persist"),
    ({"watch_map": True}, "--watch-map needs --leg fight"),
])
def test_a_bad_leg_flag_stops_before_the_manifest_is_read(tmp_path, extra, message):
    # No prepare.json exists, so only a flag check ahead of the manifest read can give this message.
    with pytest.raises(winwishaccept.AcceptanceStop, match=message):
        fsuaewishaccept.preflight(_args(tmp_path, **extra), game=SimpleNamespace(),
                                  route_for=lambda *a: pytest.fail("route read"))


def test_fs_uae_runs_no_control_branch():
    assert fsuaewishaccept.FsuaeController.control_branches is False
    assert winwishaccept.Controller.control_branches is True


@pytest.mark.parametrize("dialog, stops", [
    ({"kind": "question", "text": "Level up?", "answer": "yes"}, False),
    ({"kind": "choice", "text": "learns one new spell:", "items": ["Bless"], "picked": None}, True),
    ({"kind": "message", "text": "No room"}, True)])
def test_a_choice_or_message_dialog_stops_the_click_and_every_dialog_is_logged(
        tmp_path, monkeypatch, dialog, stops):
    from tools.gui import windowbuttons

    controller, _game, wish, _ = _controller(tmp_path, monkeypatch)
    wish.window = SimpleNamespace(map=object())
    monkeypatch.setattr(windowbuttons, "click", lambda *a, **k: {"error": None, "dialogs": [dialog]})
    if stops:
        with pytest.raises(winwishaccept.AcceptanceStop, match=dialog["kind"]):
            controller._click(automation_id="card_0_level_up")
    else:
        controller._click(automation_id="card_0_level_up")
    logged = [e for e in _events(tmp_path) if e["event"] == "click_dialogs"]
    assert logged[0]["dialogs"] == [dialog]


def test_the_level_up_card_check_reads_the_real_window_listing(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMainWindow

    from automap.actionbar import ActionBar, FastTravelBar
    from automap.panel import MessagesPanel, RosterPanel
    from tools.gui import windowbuttons
    from wish.ui_window import Ui_WishWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    QApplication.instance() or QApplication([])
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    messages = MessagesPanel(root)
    window = SimpleNamespace(root=root, messages=messages, roster=RosterPanel(root),
                             actions_bar=ActionBar(root, actions=[], say=messages.say),
                             fasttravel_bar=FastTravelBar(root, say=messages.say))
    window.roster.cards[0].name.setText("MAGNUS")
    controller, _game, _wish, _ = _controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_controls_listing", lambda: windowbuttons.listing(window))
    clicks = []
    monkeypatch.setattr(controller, "_click", lambda label=None, automation_id=None: clicks.append(automation_id))

    def context(member):
        return {"kind": "levelup", "slot": 0, "member": member, "evidence": [], "clicks": []}

    controller._unique_action(automation_id="card_0_level_up", context=context("MAGNUS"))
    assert clicks == ["card_0_level_up"]
    with pytest.raises(winwishaccept.AcceptanceStop, match="does not name"):
        controller._unique_action(automation_id="card_0_level_up", context=context("OTHER"))


# -- the fight leg: Wish's write log, the fight memory and the key ----------------------------


class FakeDebugger:
    """A transport `AmigaTarget.write` hands its bytes to, as `FsuaeGdb.write_memory` takes them."""

    halts_machine = False

    def __init__(self, fail=False):
        self.written, self.fail = [], fail

    def write_memory(self, addr, data, verify=True):
        if self.fail:
            raise amiga.GuestError("the emulator answered 'E01'")
        self.written.append((addr, bytes(data)))


def _amiga_target(fail=False):
    return amiga.AmigaTarget(FakeDebugger(fail), amiga.MACHINES[GAME_KEY])


@pytest.fixture
def write_log(tmp_path):
    """A `WishWriteLog` over a Wish target the test can change, removed again after the test."""
    seen = {"target": _amiga_target()}
    log = fsuaewishaccept.WishWriteLog(tmp_path / "writes.jsonl", lambda: 1.5,
                                       lambda: seen["target"])
    original = amiga.AmigaTarget.write
    log.install()
    try:
        yield log, seen
    finally:
        log.remove()
        assert amiga.AmigaTarget.write is original


def test_every_route_wish_writes_through_reaches_the_write_log(write_log):
    from automap import actionbar, amigalevelup
    from automap import actions as engine

    log, seen = write_log
    wish = seen["target"]
    engine._write_all(wish, [(0x40000, b"\x00")])               # the five actions and the watcher
    amigalevelup.WriteLog(wish).write(0x40010, b"\x01\x02")     # Level up's write_plan
    with actionbar._noting_write_failures(wish, []):            # the action bar's click
        wish.write(0x40020, b"\x03")
    assert log.made == [(0x40000, b"\x00"), (0x40010, b"\x01\x02"), (0x40020, b"\x03")]
    assert wish.debugger.written == log.made
    rows = [json.loads(line) for line in log.path.read_text().splitlines()]
    assert [(r["write"], r["address"], r["data"], r["error"]) for r in rows] == [
        (1, "0x40000", "00", None), (2, "0x40010", "0102", None), (3, "0x40020", "03", None)]


def test_a_write_by_another_target_is_not_wishs_and_is_not_logged(write_log):
    log, seen = write_log
    driver = _amiga_target()
    driver.write(0x40000, b"\x01")
    seen["target"] = None                    # Wish detached: nothing it could write
    _amiga_target().write(0x40001, b"\x02")
    assert log.made == [] and not log.path.exists()
    assert driver.debugger.written == [(0x40000, b"\x01")]


def test_a_write_that_raised_is_logged_with_its_error_and_still_raises(write_log):
    log, seen = write_log
    seen["target"] = _amiga_target(fail=True)
    with pytest.raises(amiga.GuestError):
        seen["target"].write(0x40000, b"\x00")
    row = json.loads(log.path.read_text())
    assert log.made == [(0x40000, b"\x00")] and row["error"].startswith("GuestError")


def _fight_args(tmp_path, **extra):
    return _args(tmp_path, leg="fight", **extra)


def _fight_controller(tmp_path, monkeypatch, *, title="darkness", layout=GAME_KEY, **flags):
    clock, game = FakeClock(), FakeGame(tmp_path)
    wish = FakeWish(clock)
    made = []

    def machine(port):
        made.append((FakeGdb(), FakeTarget(), amiga.MACHINES[layout]))
        return made[-1]

    info = {"media": {}, "fight": {"entry": "walk", "survive": False, "place": None,
                                   "pin": None, "loaded": None, "stage": None, "walk": None}}
    controller = fsuaewishaccept.FsuaeController(
        _fight_args(tmp_path, **flags), game=game, guards=lambda state, crop: True,
        route=_route(title=title), info=info, wish_run=wish, machine=machine, clock=clock)
    monkeypatch.setattr(fsuaewishaccept.fsuaegdb, "helper_row",
                        lambda port: {"alive": False, "pid": None})
    monkeypatch.setattr(controller, "_enter_environment", lambda: None)
    monkeypatch.setattr(controller, "_leave_environment", lambda: None)
    monkeypatch.setattr(controller, "_shoot_window", lambda path: path.write_bytes(b"png"))
    return controller, game, wish, made


def test_the_fight_leg_installs_the_write_log_and_cleanup_removes_it(tmp_path, monkeypatch):
    original = amiga.AmigaTarget.write
    controller, _game, wish, _made = _fight_controller(tmp_path, monkeypatch)
    controller._up()
    try:
        assert amiga.AmigaTarget.write is not original
        wish.window.session = SimpleNamespace(target=_amiga_target())
        wish.window.session.target.write(0x40000, b"\x00")
        assert controller._wish_writes() == [(0x40000, b"\x00")]
    finally:
        controller._cleanup()
    assert amiga.AmigaTarget.write is original
    assert controller.summary["wish_writes"] == {
        "log": str(tmp_path / fsuaewishaccept.WRITE_LOG), "writes": 1, "failure": None}


def test_the_mapping_leg_keeps_no_write_log(tmp_path, monkeypatch):
    controller, _game, _wish, _made = _controller(tmp_path, monkeypatch)
    assert controller._wish_writes() is None


def test_the_queued_key_is_pressed_at_once_with_wish_reading_and_no_lead(tmp_path, monkeypatch):
    controller, game, wish, _made = _fight_controller(tmp_path, monkeypatch)
    wish.open()
    began, counted = wish.clock.now, controller.action_commands
    schedule = controller._scheduled_key("N", show_map=True)
    assert [call for call in game.calls if call[0] == "press"] == [("press", "N")]
    assert schedule["lead_frames"] == 0 and schedule["tab_shown_s"] == 0.0
    assert wish.clock.now - began >= winwishaccept.WALK_SETTLE
    assert wish.window.mapper._ticks >= fsuaewishaccept.WISH_READS_PER_KEY
    # The caller counts the key, as it does for WinUAE's queued one.
    assert controller.action_commands == counted
    with pytest.raises(winwishaccept.AcceptanceStop, match="while Wish does not read"):
        controller._scheduled_key("N", show_map=False)


def test_the_fight_memory_reads_through_a_helper_client_of_its_own(tmp_path, monkeypatch):
    from tools.amiga import cursefight, ssbfight

    monkeypatch.setattr(amiga, "WinuaePipe", lambda **kw: pytest.fail("WinUAE pipe opened"))
    controller, _game, _wish, made = _fight_controller(tmp_path, monkeypatch, title="ssb")
    memory = controller._fight_memory(lambda holder, route: ssbfight.Memory(holder), "h",
                                      controller.route)
    target = memory.target()
    assert isinstance(target, cursefight.Serial)
    assert target._inner is made[0][1] and target._lock is memory._lock
    assert memory.target() is target and len(made) == 1
    made[0][0].lost = True                       # the client went: a new one is opened
    assert memory.target() is not target and len(made) == 2 and made[0][0].closed
    controller._cleanup()
    assert made[1][0].closed


def test_the_fight_memory_stops_on_another_titles_helper(tmp_path, monkeypatch):
    from tools.amiga import cursefight

    controller, _game, _wish, made = _fight_controller(tmp_path, monkeypatch, title="curse")
    memory = controller._fight_memory(lambda holder, route: cursefight.Memory(holder), "h",
                                      controller.route)
    with pytest.raises(winwishaccept.AcceptanceStop, match="helper's game"):
        memory.target()
    assert made[0][0].closed


def test_the_fight_leg_runs_with_the_helper_reads_and_the_helper_fight_memory(tmp_path, monkeypatch):
    from automap import amigaparty
    from tools.amiga import amigatarget, cursefight

    controller, _game, _wish, made = _fight_controller(tmp_path, monkeypatch)
    route = SimpleNamespace(title="darkness", game_key=GAME_KEY)
    monkeypatch.setitem(amigaparty.ROWS, GAME_KEY, SimpleNamespace(
        current=0x10, control=amigaparty.Spot(0), quickfight=amigaparty.Spot(1),
        hp=amigaparty.Spot(2), record_size=8, name=4))
    original = winwishaccept._fight_memory
    seen = {}

    def run_fight():
        seen["connect"] = amigatarget.connect_pipe
        seen["target"] = winwishaccept._fight_memory("h", route).target()
        return {"ok": True}

    monkeypatch.setattr(controller, "run_fight", run_fight)
    assert controller.run_title() == {"ok": True}
    assert seen["connect"] == controller._connect
    assert isinstance(seen["target"], cursefight.Serial) and seen["target"]._inner is made[0][1]
    assert winwishaccept._fight_memory is original


class _EdgeWish(FakeWish):
    """Wish's watcher: once the key has landed, its session target clears QUICK on each chosen
    member through `AmigaTarget.write`, and the game reaches the after-fight mode."""

    def __init__(self, clock, world, game):
        super().__init__(clock)
        self.world, self.game = world, game

    def pump(self, seconds):
        super().pump(seconds)
        world = self.world
        if ("press", "N") in self.game.calls and world["mode"] != 6:
            world["mode"] = 6
            for member in world["members"]:
                if member["raw"][1] == 1 and not member["raw"][0] & 0x80:
                    member["raw"][1] = 0
                    self.window.session.target.write(member["address"] + 1, b"\x00")
            for address, data in world["extra"]:
                self.window.session.target.write(address, data)


def _fs_edge(tmp_path, monkeypatch, *, extra=(), removed=True):
    from automap import amigaparty

    monkeypatch.setitem(amigaparty.ROWS, GAME_KEY, SimpleNamespace(
        mode=0x5B12, combat_value=5, after_fight_value=6, combat_legal=frozenset(),
        control=amigaparty.Spot(0, 1, 0x80), quickfight=amigaparty.Spot(1)))
    controller, game, _wish, _made = _fight_controller(tmp_path, monkeypatch, watch=True)
    world = {"mode": 5, "extra": list(extra), "members": [
        {"address": 0x41000, "raw": bytearray([0, 1, 7])},
        {"address": 0x41100, "raw": bytearray([0x80, 1, 7])}]}
    wish = _EdgeWish(controller.clock, world, game)
    controller.wish = wish
    wish.open()
    wish.window.session = SimpleNamespace(target=_amiga_target())
    controller.write_log = fsuaewishaccept.WishWriteLog(
        tmp_path / fsuaewishaccept.WRITE_LOG, lambda: 0.0, controller._wish_target)
    monkeypatch.setattr(controller, "_await", lambda state, limit=90, interstitials=(): {
        "raw": f"{state}.raw.png"})
    monkeypatch.setattr(controller, "_read_mode", lambda: world["mode"])
    monkeypatch.setattr(controller, "_action_readback", lambda: [
        {"slot": at, "name": f"M{at}", "address": m["address"], "raw": bytes(m["raw"]).hex(),
         "items": []} for at, m in enumerate(world["members"])])
    monkeypatch.setattr(controller, "_controls_listing", lambda: [
        "ListItem|Removed quickfight from 1 character.|messages|enabled=True|visible=True"
        if removed else "ListItem|Party|messages|enabled=True|visible=True"])
    return controller, game


def test_the_fs_uae_edge_grades_watch_a_from_wishs_own_writes(tmp_path, monkeypatch):
    controller, game = _fs_edge(tmp_path, monkeypatch)
    controller.write_log.install()
    try:
        assert controller._watch_edge("N") is True
    finally:
        controller.write_log.remove()
    assert controller._wish_writes() == [(0x41001, b"\x00")]
    wish_row = controller.summary["watch_a"]
    assert (wish_row["status"], wish_row["reason"]) == ("awaiting image review", None)
    assert controller.summary["watch_control_b"]["reason"] == winwishaccept.CONTROL_NOT_RUN
    assert [c for c in game.calls if c[0] in ("snapshot", "restore", "press")] == [("press", "N")]
    rows = [json.loads(line) for line in (tmp_path / fsuaewishaccept.WRITE_LOG).read_text().splitlines()]
    assert [(r["address"], r["data"]) for r in rows] == [("0x41001", "00")]


@pytest.mark.parametrize("extra, removed, reason", [
    ([(0x41002, b"\x09")], True, "Wish wrote 00 at 0x41001, 09 at 0x41002"),
    ((), False, "Messages holds no 'Removed quickfight' line")])
def test_the_fs_uae_edge_fails_on_a_write_or_a_message_wish_should_not_have_made(
        tmp_path, monkeypatch, extra, removed, reason):
    controller, _game = _fs_edge(tmp_path, monkeypatch, extra=extra, removed=removed)
    controller.write_log.install()
    try:
        controller._watch_edge("N")
    finally:
        controller.write_log.remove()
    wish_row = controller.summary["watch_a"]
    assert wish_row["status"] == "failed" and wish_row["reason"].startswith(reason)


def _fight_preflight(tmp_path, monkeypatch, **extra):
    media, mounted = _ssb_media(tmp_path)
    (tmp_path / "prepare.json").write_text("{}")
    route = _route(media=media, mounted=mounted)
    states = {"title", "world", "combat_bar"}
    plan = SimpleNamespace(entry="walk", survive=True, extra_guards={"combat_bar": {"rule": 1}})
    monkeypatch.setattr(winwishaccept, "leg_preflight", lambda args, route, manifest: {
        "persist": None, "plan": plan, "specimen": {"place": {"x": 1}, "pin": "abc"},
        "stage": None, "states": states})
    seen = []

    def export(args, route, wanted=None, *, extra=None):
        seen.append((wanted, extra))
        return "guards", {"export": "x"}

    binary = tmp_path / "fs-uae"
    binary.write_bytes(b"emulator")
    result = fsuaewishaccept.preflight(
        _fight_args(tmp_path, **extra), game=FakeGame(tmp_path),
        route_for=lambda title, manifest, **legs: route, binary=lambda: binary,
        kickstart=lambda: binary, driver=lambda: {"sha": "x", "dirty": False}, export=export,
        journal_check=lambda executable: None)
    return result, seen, states, plan


def test_the_fight_leg_passes_preflight_with_its_plan_and_merged_guards(tmp_path, monkeypatch):
    (_route_, guards, info), seen, states, plan = _fight_preflight(
        tmp_path, monkeypatch, watch=True, watch_map=True)
    assert info["leg"] == "fight" and guards == "guards"
    assert info["fight"] == {"entry": "walk", "survive": True, "place": {"x": 1}, "pin": "abc",
                             "loaded": None, "stage": None, "walk": None}
    assert seen == [(states, plan.extra_guards)]


def test_the_guard_export_merges_the_fight_guards_before_the_state_check(tmp_path, monkeypatch):
    guard_path = tmp_path / "maps" / f"guards_{fsuaewishaccept.guardmaps.FILES['ssb']}.json"
    guard_path.parent.mkdir()
    guard_path.write_text("{}")
    route = SimpleNamespace(title="ssb", guard_path=guard_path)

    def export(argv):
        out = pathlib.Path(argv[argv.index("--out") + 1])
        (out / "guards.json").write_text(json.dumps({"world": 1}))
        return 0

    def merge(path, extra):
        path.write_text(json.dumps({**json.loads(path.read_text()), **extra}))

    monkeypatch.setattr(fsuaewishaccept.guardmaps, "main", export)
    monkeypatch.setattr(winwishaccept, "_merge_guards", merge)
    monkeypatch.setattr(fsuaewishaccept.screens, "PixelGuards", lambda path: SimpleNamespace(
        rules=json.loads(pathlib.Path(path).read_text())))
    guards, _info = fsuaewishaccept._export_guards(
        _args(tmp_path), route, {"world", "combat_bar"}, extra={"combat_bar": 2})
    assert guards.rules == {"world": 1, "combat_bar": 2}


def test_a_fight_stage_on_another_leg_stops_in_preflight(tmp_path):
    (tmp_path / "prepare.json").write_text(json.dumps({"fight": {}}))
    with pytest.raises(winwishaccept.AcceptanceStop, match="fight stage runs only with --leg fight"):
        fsuaewishaccept.preflight(_args(tmp_path), game=FakeGame(tmp_path),
                                  route_for=lambda *a, **k: pytest.fail("route read"))


def test_a_key_whose_settle_the_route_time_cuts_short_says_it_was_sent_and_what_wish_read(
        tmp_path, monkeypatch):
    controller, game, wish, _made = _fight_controller(tmp_path, monkeypatch)
    wish.open()
    monkeypatch.setattr(controller, "left", lambda limit: min(limit, 1.0))
    with pytest.raises(winwishaccept.AcceptanceStop,
                       match=r"key N was sent, then the route time ran out: Wish read the game "
                             r"[3-9] times in the \d+\.\d s after it"):
        controller._scheduled_key("N", show_map=True)
    assert [call for call in game.calls if call[0] == "press"] == [("press", "N")]


def test_a_log_fault_never_replaces_the_writes_own_outcome(tmp_path):
    def broken_clock():
        raise RuntimeError("clock gone")

    seen = {"target": _amiga_target()}
    log = fsuaewishaccept.WishWriteLog(tmp_path / "writes.jsonl", broken_clock, lambda: seen["target"])
    log.install()
    try:
        assert seen["target"].write(0x40000, b"\x00") is None
        seen["target"] = _amiga_target(fail=True)
        with pytest.raises(amiga.GuestError):
            seen["target"].write(0x40001, b"\x01")
    finally:
        log.remove()
    assert log.made == [(0x40000, b"\x00"), (0x40001, b"\x01")]
    assert log.failure == "RuntimeError: clock gone"


def test_cleanup_closes_a_fight_client_whose_lock_a_stuck_read_holds(tmp_path, monkeypatch):
    import threading

    from tools.amiga import ssbfight

    monkeypatch.setattr(fsuaewishaccept, "CLOSE_LOCK_WAIT", 0.1)
    controller, _game, _wish, made = _fight_controller(tmp_path, monkeypatch, title="ssb")
    memory = controller._fight_memory(lambda holder, route: ssbfight.Memory(holder), "h",
                                      controller.route)
    memory.target()
    held, release = threading.Event(), threading.Event()

    def stuck_read():
        with memory._lock:
            held.set()
            release.wait(10)

    worker = threading.Thread(target=stuck_read, daemon=True)
    worker.start()
    held.wait(5)
    try:
        controller._cleanup()
        assert made[0][0].closed and memory._target is None
        assert controller.summary["cleanup"]["errors"] == []
        assert ("release",) in _game.calls or not controller.claimed
    finally:
        release.set()
        worker.join(5)


def test_a_fight_leg_that_raises_puts_back_the_fight_memory_and_the_pipe(tmp_path, monkeypatch):
    from tools.amiga import amigatarget

    controller, _game, _wish, _made = _fight_controller(tmp_path, monkeypatch)
    memory, pipe = winwishaccept._fight_memory, amigatarget.connect_pipe

    def run_fight():
        assert winwishaccept._fight_memory is not memory
        raise RuntimeError("fight driver broke")

    monkeypatch.setattr(controller, "run_fight", run_fight)
    with pytest.raises(RuntimeError, match="fight driver broke"):
        controller.run_title()
    assert winwishaccept._fight_memory is memory and amigatarget.connect_pipe is pipe
