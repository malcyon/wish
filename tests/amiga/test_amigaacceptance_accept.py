"""The accept mode of the Silver Blades driver: route, guards, interstitials, verdicts and evidence."""

from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import sys
import types

import pytest

from automap.amiga import GuestError
from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigaacceptance_measure as measure
from tests.amiga.fakes import FakeGameMemory, fake_stage_helper
from tests.amiga.test_amigaacceptance import _audio_proof, _sha
from tests.amiga.test_amigaacceptance_measure import ScreenGuest, _keys, _menu_manifest
from tools.amiga import acceptance, route_silver_blades, winuaesession
from tools.amiga.amigatarget import A4_BIAS

clock = measure.clock  # the fixture that replaces the driver's time and sleep
BEFORE = {"area": 16, "x": 3, "y": 5, "facing": 2}
NAMES = ["GUY", "PAINE"]
KEYS = "P L C V I E E S B B NP8 NP8 E S D N".split()
STATES = ["title", "01-party_menu", "02-load_picker", "03-loaded_menu", "04-sheet",
          "05-items", "06-sheet", "07-loaded_menu", "08-save_picker", "09-post_write",
          "10-journal", "11-world", "12-world", "13-world", "14-camp",
          "15-camp_save_picker", "16-exit_game", "17-camp"]


def _reading(x=3, y=5, facing=2, area=16):
    return {"sha256": "0" * 64, "names": NAMES,
            "place": {"area": area, "x": x, "y": y, "facing": facing},
            "inventory": {"members": [], "joined_inventory_expected": True}}


class MapGuard:
    """A guard map that recognises a state by the name of the crop it is shown.

    `on` replaces the rule of a state with a function of the crop's path.
    """

    ALL = ("title", "party_menu", "load_picker", "loaded_menu", "sheet", "items",
           "save_picker", "journal", "world", "camp", "camp_save_picker", "exit_game")

    def __init__(self, states=ALL, on=None):
        self.states, self.on = set(states), dict(on or {})

    def __contains__(self, state):
        return state in self.states

    def shown(self, path):
        stem = path.stem.split("-after-")[0]
        stem = stem.split("-", 1)[1] if stem[:2].isdigit() else stem
        return "loaded_menu" if stem == "post_write" else stem

    def __call__(self, state, path):
        if state in self.on:
            return self.on[state](path)
        return state in self.states and self.shown(path) == state


class AcceptGuest(ScreenGuest):
    """Writes slot B on the first `B` and slot D on `D`, and records when each key went."""

    def __init__(self, clock, *, raises=None, still_world=False):
        super().__init__(clock)
        self.written_b, self.raises, self.pressed = False, raises, []
        self.still_world = still_world

    def press(self, holder, key, timeout=None):
        super().press(holder, key, timeout)
        self.pressed.append((key, self.clock.now))
        if self.raises and len(self.pressed) == self.raises[0]:
            raise self.raises[1]
        if key == "B" and not self.written_b:
            self.written_b = True
            self._save("B")
        elif key == "D":
            self._save("D")

    def _save(self, letter):
        remote = self.drives[0]
        disk = AmigaDisk(self.remote[remote])
        disk.write_file(f"/SAVE/savgam{letter}.sav", f"game wrote {letter}".encode())
        self.remote[remote] = disk.to_bytes()

    def grab(self, state, raw, cropped, timeout=None):
        super().grab(state, raw, cropped, timeout)
        if self.still_world and "world" in state:
            cropped.write_bytes(b"the world bar")
        return True


class Answer:
    def __init__(self, guest, replies=None):
        self.guest, self.replies, self.calls = guest, list(replies or []), []

    def __call__(self, holder, adf, timeout):
        self.calls.append((len(self.guest.pressed), self.guest.clock.now, str(adf)))
        return self.replies.pop(0) if self.replies else (0, "answered")


def _manifest(tmp_path):
    manifest = _menu_manifest(tmp_path)
    boot = tmp_path / "boot-source.adf"
    boot.write_bytes(b"registered side A")
    data = json.loads(manifest.read_text())
    data["boot_source"] = {"path": str(boot), "sha256": _sha(boot)}
    manifest.write_text(json.dumps(data))
    return manifest


@pytest.fixture
def readings(monkeypatch):
    by_letter = {"B": _reading(), "D": _reading(y=7)}
    monkeypatch.setattr(acceptance, "_slot_reading", lambda fetched, letter: by_letter[letter])
    return by_letter


def _accept(tmp_path, clock, *, guest=None, guard=None, identity=None, answer=None,
            manifest=None, **kw):
    guest = guest or AcceptGuest(clock)
    guest.answer = answer or Answer(guest)
    kw.setdefault("preflight", lambda python: None)
    kw.setdefault("journal_python", "python-with-numpy")
    result = acceptance.run_recon(
        manifest or _manifest(tmp_path), guest=guest,
        guard=guard or MapGuard(),
        identity=identity or _IdentityMap(), holder="wish672-test",
        audio_proof=_audio_proof(tmp_path), accept=True, answer=guest.answer, **kw)
    return guest, result


def _events(tmp_path):
    lines = (tmp_path / "recon1" / "run.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


class _IdentityMap:
    """Identity rules named as a map, with a verdict per state."""

    def __init__(self, fail=()):
        self.fail = set(fail)

    def __contains__(self, state):
        return state in ("sheet", "loaded_menu")

    def __call__(self, state, path):
        return state not in self.fail


def test_the_route_table_is_the_plan_s_seventeen_steps():
    assert [(k, s, kind) for k, s, kind in route_silver_blades.ACCEPT_ROUTE] == [
        ("P", "party_menu", "key"), ("L", "load_picker", "key"),
        ("C", "loaded_menu", "key"), ("V", "sheet", "key"), ("I", "items", "key"),
        ("E", "sheet", "key"), ("E", "loaded_menu", "key"), ("S", "save_picker", "key"),
        ("B", "loaded_menu", "write"), ("B", "journal", "key"),
        (None, "world", "answer"), ("NP8", "world", "move"), ("NP8", "world", "move"),
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("D", "exit_game", "write"), ("N", "camp", "key")]
    assert (route_silver_blades.MENU_SAVE_LETTER == "B"
            and route_silver_blades.CAMP_SAVE_LETTER == "D")


def test_accept_presses_the_route_and_answers_the_journal_once(
        tmp_path, clock, readings):
    guest, result = _accept(tmp_path, clock)
    assert _keys(guest) == KEYS
    assert "RET" not in _keys(guest) and "Y" not in _keys(guest)
    assert [c[1] for c in guest.calls if c[0] == "grab"] == STATES
    answers = guest.answer.calls
    assert len(answers) == 1 and answers[0][0] == 10  # after the second B
    assert answers[0][2] == str(tmp_path / "boot-source.adf")
    # B writes at the menu save and again as BEGIN; D writes once.
    assert [i for i, k in enumerate(_keys(guest)) if k == "B"] == [8, 9]
    assert _keys(guest).count("D") == 1 and _keys(guest).index("D") == 14
    assert result["error"] == "" and result["completed"] is True


def test_accept_passes_when_d_is_two_squares_along_the_facing(tmp_path, clock, readings):
    _, result = _accept(tmp_path, clock)
    assert result["read"]["verdicts"] == [
        "slot B: did not move", "slot D: moved 2 squares from 3,5 to 3,7"]
    assert result["read"]["squares_moved"] == 2 and result["read"]["place_changed"]
    assert result["success"] is True and result["unguarded"] == []


@pytest.mark.parametrize("d, verdict", [
    (_reading(y=5), "slot D: did not move"),
    (_reading(y=6), "slot D: moved from 3,5 to 3,6, expected 3,7"),
    (_reading(y=8), "slot D: moved from 3,5 to 3,8, expected 3,7"),
    (_reading(y=7, facing=1), "expected 3,7"),
    (_reading(x=4, y=7), "slot D: moved from 3,5 to 4,7, expected 3,7"),
])
def test_accept_fails_when_d_is_not_exactly_two_squares_along_the_facing(
        tmp_path, clock, readings, d, verdict):
    readings["D"] = d
    _, result = _accept(tmp_path, clock)
    assert verdict in result["read"]["verdicts"][1]
    assert result["success"] is False


def test_accept_fails_when_b_is_not_the_prepared_place(tmp_path, clock, readings):
    readings["B"] = _reading(y=6)
    readings["D"] = _reading(y=8)
    _, result = _accept(tmp_path, clock)
    assert result["read"]["verdicts"][0].startswith("slot B: moved from 3,5 to 3,6")
    # D is judged from where B stood, so the run is not failed twice for one fault.
    assert result["read"]["verdicts"][1] == "slot D: moved 2 squares from 3,6 to 3,8"
    assert result["success"] is False


def test_the_step_wraps_at_the_map_edge():
    before = dict(BEFORE, y=15)
    verdict = acceptance.walk_verdict(before, _reading(y=15), _reading(y=1), 2)
    assert verdict["d_ok"] is True and verdict["squares_moved"] == 2
    assert verdict["verdicts"][1] == "slot D: moved 2 squares from 3,15 to 3,1"


def test_a_missing_or_undecodable_slot_is_named():
    verdict = acceptance.walk_verdict(BEFORE, {"missing": True, "sha256": None},
                                 {"sha256": "0" * 64, "decode_error": "X: y"}, 2)
    assert verdict["verdicts"] == ["slot B: was not written", "slot D: does not decode"]
    assert not verdict["b_ok"] and not verdict["d_ok"]


def test_accept_needs_the_names_and_the_inventory_in_slot_d(tmp_path, clock, readings):
    readings["D"] = dict(_reading(y=7), names=["GUY"])
    _, result = _accept(tmp_path, clock)
    assert "members" in " ".join(result["camp_save_problems"])
    assert result["success"] is False


def test_accept_fails_on_a_save_slot_it_did_not_name(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    real = guest._save

    def save(letter):
        real(letter)
        if letter == "D":
            real("E")

    guest._save = save
    _, result = _accept(tmp_path, clock, guest=guest)
    assert result["extra_saves"] == ["savgamE.sav"] and result["success"] is False


def test_accept_refuses_before_the_claim_without_the_recon_guards(tmp_path, clock):
    guest = AcceptGuest(clock)
    with pytest.raises(winuaesession.RouteError, match="lacks .*sheet"):
        _accept(tmp_path, clock, guest=guest,
                guard=MapGuard(set(MapGuard.ALL) - {"sheet"}))
    assert guest.calls == []


def test_accept_refuses_before_the_claim_without_identity(tmp_path, clock):
    guest = AcceptGuest(clock)
    with pytest.raises(winuaesession.RouteError, match="identity map lacks"):
        acceptance.run_recon(_manifest(tmp_path), guest=guest, guard=MapGuard(),
                        holder="wish672-test", audio_proof=_audio_proof(tmp_path),
                        accept=True, answer=lambda *a: (0, "answered"),
                        identity=None)
    assert guest.calls == []


def test_accept_refuses_before_the_claim_without_a_journal_interpreter(tmp_path, clock):
    guest = AcceptGuest(clock)
    with pytest.raises(winuaesession.RouteError, match="journal interpreter"):
        _accept(tmp_path, clock, guest=guest,
                journal_python=str(tmp_path / "no-such-python"),
                preflight=route_silver_blades.journal_preflight)
    assert guest.calls == []


def test_accept_refuses_a_manifest_without_the_boot_disk_for_the_answerer(tmp_path, clock):
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text())
    del data["boot_source"]
    manifest.write_text(json.dumps(data))
    guest = AcceptGuest(clock)
    with pytest.raises(winuaesession.RouteError, match="boot_source"):
        _accept(tmp_path, clock, guest=guest, manifest=manifest)
    assert guest.calls == []


def test_the_preflight_wants_the_imports_and_the_private_tables(tmp_path, monkeypatch):
    ran = []

    def run(argv, **kw):
        ran.append(argv)
        reader = argv[2] == route_silver_blades.JOURNAL_READER_CHECK
        return subprocess.CompletedProcess(argv, 0, b"ok\n" if reader else b"", b"")

    monkeypatch.setattr(route_silver_blades.subprocess, "run", run)
    monkeypatch.setattr(route_silver_blades.amigabladesjournal, "wheel_repo", lambda: tmp_path)
    with pytest.raises(winuaesession.RouteError, match="not a directory"):
        route_silver_blades.journal_preflight("py")
    (tmp_path / "ssb" / "analysis").mkdir(parents=True)
    route_silver_blades.journal_preflight("py")
    assert ran[-1] == ["py", "-c", "import numpy, PIL"]
    monkeypatch.setattr(route_silver_blades.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"", b""))
    with pytest.raises(winuaesession.RouteError, match="cannot import numpy"):
        route_silver_blades.journal_preflight("py")


def test_a_save_letter_that_is_a_prepared_slot_is_refused(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(acceptance, "MENU_SAVE_LETTER", route_silver_blades.SLOT_LETTER)
    guest = AcceptGuest(clock)
    with pytest.raises(winuaesession.RouteError, match="would overwrite"):
        _accept(tmp_path, clock, guest=guest)
    assert guest.calls == []


def test_an_unguarded_state_is_settled_and_the_run_is_measuring(tmp_path, clock, readings):
    guest, result = _accept(
        tmp_path, clock, guard=MapGuard(set(MapGuard.ALL) - {"camp"}))
    assert ("capture", "14-camp") in guest.calls and ("capture", "17-camp") in guest.calls
    assert result["unguarded"] == ["camp"]
    assert result["success"] is False and result["error"] == ""
    assert result["read"]["verdicts"][1].startswith("slot D: moved 2 squares")
    settled = [e for e in result["events"] if e.get("recognized") is False]
    assert len(settled) == 2


def test_a_candidate_guard_that_never_matches_falls_back_to_a_settled_capture(
        tmp_path, clock, readings):
    guest, result = _accept(tmp_path, clock, guard=MapGuard(on={"world": lambda p: False}))
    assert ("capture", "11-world") in guest.calls
    assert result["unguarded"] == ["world"] and result["error"] == ""
    assert _keys(guest) == KEYS  # the run went on past the state
    assert result["success"] is False and result["read"]["squares_moved"] == 2


def test_a_recon_state_guard_that_never_matches_still_stops_the_run(
        tmp_path, clock, readings):
    guest, result = _accept(tmp_path, clock, guard=MapGuard(on={"sheet": lambda p: False}))
    assert "sheet screen was not recognized" in result["error"]
    assert "B" not in _keys(guest) and result["unguarded"] == []
    assert result["success"] is False


def test_the_credits_are_left_with_escape_and_the_title_is_waited_for_again(
        tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    esc = lambda: "ESC" in _keys(guest)  # noqa: E731
    guard = MapGuard(on={
        "credits": lambda p: p.name == "title.png" and not esc(),
        "title": lambda p: p.name == "title.png" and esc()})
    guard.states.add("credits")
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard)
    assert _keys(guest) == ["ESC", *KEYS] and result["success"] is True


def test_a_party_menu_after_the_credits_skips_p_in_accept_and_in_recon(
        tmp_path, clock, readings):
    def guard_for(guest):
        esc = lambda: "ESC" in _keys(guest)  # noqa: E731
        guard = MapGuard(on={
            "credits": lambda p: p.name == "title.png" and not esc(),
            "title": lambda p: False,
            "party_menu": lambda p: p.name == "title.png" and esc()})
        guard.states.add("credits")
        return guard

    guest = AcceptGuest(clock)
    _accept(tmp_path, clock, guest=guest, guard=guard_for(guest))
    assert _keys(guest)[:3] == ["ESC", "L", "C"] and _keys(guest).count("P") == 0

    recon_guest = AcceptGuest(clock)
    other = tmp_path / "recon"
    other.mkdir()
    acceptance.run_recon(_manifest(other), guest=recon_guest, guard=guard_for(recon_guest),
                    holder="wish672-test", audio_proof=_audio_proof(other))
    assert _keys(recon_guest)[:3] == ["ESC", "L", "C"] and "P" not in _keys(recon_guest)


def test_the_continue_screen_is_answered_with_return(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    stuck = lambda p: p.name == "11-world.png" and "RET" not in _keys(guest)  # noqa: E731
    guard = MapGuard(on={"continue": stuck,
                         "world": lambda p: not stuck(p) and "world" in p.name})
    guard.states.add("continue")
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard)
    assert _keys(guest)[10:12] == ["RET", "NP8"] and _keys(guest).count("RET") == 1
    assert result["success"] is True


def test_the_treasure_prompt_after_the_camp_key_is_answered_with_no(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    asked = lambda p: p.name == "14-camp.png" and "N" not in _keys(guest)  # noqa: E731
    guard = MapGuard(on={"treasure": asked,
                         "camp": lambda p: "camp" in p.name and not asked(p)})
    guard.states.add("treasure")
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard)
    keys = _keys(guest)
    assert keys[12:15] == ["E", "N", "S"] and keys.count("N") == 2  # the answer, then the route's own
    assert result["success"] is True


def test_a_question_after_the_camp_save_is_answered(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    guest.answer = answer = Answer(guest)
    asked = lambda p: p.name == "16-exit_game.png" and len(answer.calls) < 2  # noqa: E731
    guard = MapGuard(on={"journal": lambda p: p.name == "10-journal.png" or asked(p),
                         "exit_game": lambda p: p.name == "16-exit_game.png" and not asked(p)})
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard, answer=answer)
    assert len(answer.calls) == 2 and answer.calls[1][0] == 15  # after D
    assert _keys(guest) == KEYS and result["success"] is True


def test_a_sheet_of_another_member_stops_the_run_before_any_save(tmp_path, clock, readings):
    guest, result = _accept(tmp_path, clock, identity=_IdentityMap(fail={"sheet"}))
    assert result["error"].endswith("sheet shows another member")
    assert "B" not in _keys(guest) and result["success"] is False


def test_a_loaded_menu_of_another_party_stops_the_run(tmp_path, clock, readings):
    guest, result = _accept(tmp_path, clock, identity=_IdentityMap(fail={"loaded_menu"}))
    assert result["error"].endswith("loaded_menu shows another party")
    assert _keys(guest) == ["P", "L", "C"]


def test_no_challenge_on_screen_is_retried_until_the_limit(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    answer = Answer(guest, [(1, "no challenge on screen")] * 100)
    _, result = _accept(tmp_path, clock, guest=guest, answer=answer)
    assert "no journal challenge on screen within 120s" in result["error"]
    assert len(answer.calls) == 25 and _keys(guest) == KEYS[:10]
    assert result["success"] is False


def test_a_challenge_that_appears_late_is_answered_on_a_later_try(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    answer = Answer(guest, [(1, "no challenge on screen")] * 3)
    _, result = _accept(tmp_path, clock, guest=guest, answer=answer)
    assert len(answer.calls) == 4 and result["success"] is True
    gaps = [b[1] - a[1] for a, b in zip(answer.calls, answer.calls[1:])]
    assert gaps == [acceptance.GUARD_POLL] * 3


def test_any_other_answer_stops_the_run(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    _, result = _accept(tmp_path, clock, guest=guest,
                        answer=Answer(guest, [(1, "")]))
    assert "journal answerer ended 1" in result["error"]
    assert _keys(guest) == KEYS[:10]


def test_a_move_key_is_pressed_once_even_when_the_screen_did_not_change(
        tmp_path, clock, readings):
    guest, result = _accept(tmp_path, clock, guest=AcceptGuest(clock, still_world=True))
    assert _keys(guest).count("NP8") == 2
    moves = [e for e in result["events"] if "crop_changed" in e]
    assert [e["crop_changed"] for e in moves] == [False, False] and len(moves) == 2


def test_each_state_waits_its_minimum_before_the_first_look(tmp_path, clock, readings):
    guest, _ = _accept(tmp_path, clock,
                       min_waits={**route_silver_blades.default_min_waits(),
                                  **route_silver_blades.ACCEPT_MIN_WAITS})
    first = {}
    for name, at in guest.at:
        first.setdefault(name, at)
    press = {i + 1: at for i, (_, at) in enumerate(guest.pressed)}
    answered = guest.answer.calls[0][1]
    assert first["09-post_write"] - press[9] == 20
    assert first["10-journal"] - press[10] == 45
    assert first["11-world"] - answered == 20
    assert first["12-world"] - press[11] == 5 and first["13-world"] - press[12] == 5
    assert first["14-camp"] - press[13] == 10
    assert first["15-camp_save_picker"] - press[14] == 10
    assert first["16-exit_game"] - press[15] == 20
    assert first["17-camp"] - press[16] == 10


def test_run_jsonl_has_one_event_per_line_with_event_and_t(tmp_path, clock, readings):
    _accept(tmp_path, clock, guard=MapGuard(set(MapGuard.ALL) - {"camp"}))
    events = _events(tmp_path)
    assert all(isinstance(e["event"], str) and isinstance(e["t"], float) for e in events)
    assert {"claim", "start", "grab", "recognized", "settled", "key", "write", "answer",
            "stop", "fetch", "release", "read"} <= {e["event"] for e in events}
    assert events[0]["event"] == "claim"
    assert [e["key"] for e in events if e["event"] == "write"] == ["B", "D"]
    summary = json.loads((tmp_path / "recon1" / "summary.json").read_text())
    assert summary["completed"] is True and summary["lost"] is None
    assert summary["unguarded"] == ["camp"] and "verdicts" in summary["read"]


def test_a_terminated_run_still_stops_fetches_and_releases(tmp_path, clock, readings):
    guest = AcceptGuest(clock, raises=(3, winuaesession.Terminated("signal 15")))
    guest, result = _accept(tmp_path, clock, guest=guest)
    assert [c[0] for c in guest.calls if c[0] in ("stop", "get", "release")] == [
        "stop", "get", "get", "release"]
    assert result["lost"].startswith("Terminated") and result["completed"] is False
    assert result["success"] is False
    lost = [e for e in _events(tmp_path) if e["event"] == "lost"]
    assert len(lost) == 1
    summary = json.loads((tmp_path / "recon1" / "summary.json").read_text())
    assert summary["lost"] == result["lost"]


needs_posix_signals = pytest.mark.skipif(
    not hasattr(signal, "pthread_sigmask"), reason="this platform has no POSIX signals")


@needs_posix_signals
def test_the_installed_handler_raises_terminated_and_is_restored():
    old = signal.getsignal(signal.SIGTERM)
    with winuaesession.terminating():
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not old
        with pytest.raises(winuaesession.Terminated):
            handler(signal.SIGTERM, None)
        with pytest.raises(winuaesession.Terminated):
            os.kill(os.getpid(), signal.SIGTERM)
    assert signal.getsignal(signal.SIGTERM) is old


def _main(tmp_path, clock, monkeypatch, guest, capsys):
    manifest = _manifest(tmp_path)
    guest.answer = Answer(guest)
    monkeypatch.setattr(acceptance, "WinGuest", lambda: guest)
    monkeypatch.setattr(acceptance, "PixelGuards", lambda path: MapGuard())
    monkeypatch.setattr(acceptance, "journal_preflight", lambda python: None)
    monkeypatch.setattr(acceptance, "run_journal_answer",
                        lambda python, holder, adf, timeout: guest.answer(holder, adf, timeout))
    argv = ["accept", "--manifest", str(manifest), "--guards", "g.json",
            "--identity", "i.json", "--journal-python", "py",
            "--audio-proof", str(_audio_proof(tmp_path))]
    code = acceptance.main(["accept", "--title", "ssb", *argv[1:]])
    return code, capsys.readouterr().out


def test_main_exits_zero_and_prints_the_verdicts_on_success(
        tmp_path, clock, readings, monkeypatch, capsys):
    code, out = _main(tmp_path, clock, monkeypatch, AcceptGuest(clock), capsys)
    assert code == 0
    assert "slot B: did not move" in out and "slot D: moved 2 squares from 3,5 to 3,7" in out


def test_main_exits_one_when_d_is_at_the_prepared_place(
        tmp_path, clock, readings, monkeypatch, capsys):
    readings["D"] = _reading(y=5)
    code, out = _main(tmp_path, clock, monkeypatch, AcceptGuest(clock), capsys)
    assert code == 1 and "slot D: did not move" in out


def _record_cli(monkeypatch):
    seen = []
    guest = object()
    monkeypatch.setattr(acceptance, "WinGuest", lambda: guest)
    monkeypatch.setattr(acceptance, "PixelGuards", lambda path: ("guards", path))

    def run(*args, **kwargs):
        seen.append((args, kwargs))
        return {"success": True, "error": None, "unguarded": [],
                "read": {"verdicts": ["slot B: did not move"]}}

    monkeypatch.setattr(acceptance, "run_recon", run)
    return seen, guest


def test_silver_blades_measure_forwards_route_waits_and_default_attempt(
        tmp_path, monkeypatch, capsys):
    seen, guest = _record_cli(monkeypatch)
    manifest = tmp_path / "prepare.json"
    assert acceptance.main(["measure", "--title", "ssb", "--manifest", str(manifest),
                            "--audio-proof", "mute.json", "--holder", "fixed"]) == 0
    args, kw = seen[0]
    assert args == (manifest,) and kw["guest"] is guest
    assert kw["route"] == route_silver_blades.ROUTE
    assert kw["write_keys"] == ("B",) and kw["measure"] is True
    assert kw["min_waits"] == route_silver_blades.default_min_waits()
    assert kw["holder"] == "fixed" and kw["attempt"] == "recon1"
    assert set(json.loads(capsys.readouterr().out.splitlines()[0])) == {"success", "error", "summary"}


def test_silver_blades_measure_forwards_custom_route_and_write_keys(
        tmp_path, monkeypatch):
    seen, _guest = _record_cli(monkeypatch)
    argv = ["measure", "--title", "ssb", "--manifest", str(tmp_path / "prepare.json"),
            "--audio-proof", "mute.json", "--route", "esc:party_menu, L:load_picker",
            "--write-keys", "b, w"]
    assert acceptance.main(argv) == 0
    kw = seen[0][1]
    route = (("ESC", "party_menu"), ("L", "load_picker"))
    assert kw["route"] == route
    assert kw["write_keys"] == ("B", "W")
    assert kw["min_waits"] == route_silver_blades.default_min_waits(route)


def test_silver_blades_measure_rejects_invalid_custom_route_and_keys(
        monkeypatch, capsys):
    monkeypatch.setattr(acceptance, "WinGuest", lambda: pytest.fail("guest created"))
    argv = ["measure", "--title", "ssb", "--manifest", "m.json",
            "--audio-proof", "mute.json"]
    assert acceptance.main([*argv, "--route", "ESC"]) == 2
    assert "route step" in capsys.readouterr().err
    assert acceptance.main([*argv, "--write-keys", "B,"]) == 2
    assert "empty entry" in capsys.readouterr().err


def test_silver_blades_accept_forwards_identity_journal_and_waits(
        tmp_path, monkeypatch, capsys):
    seen, guest = _record_cli(monkeypatch)
    manifest = tmp_path / "prepare.json"
    assert acceptance.main(["accept", "--title", "ssb", "--manifest", str(manifest),
                            "--guards", "guards.json", "--identity", "identity.json",
                            "--journal-python", "python", "--audio-proof", "mute.json"]) == 0
    args, kw = seen[0]
    assert args == (manifest,) and kw["guest"] is guest
    assert kw["guard"] == ("guards", acceptance.pathlib.Path("guards.json"))
    assert kw["identity"] == ("guards", acceptance.pathlib.Path("identity.json"))
    assert kw["journal_python"] == "python" and kw["accept"] is True
    assert kw["attempt"] == "accept1" and kw["holder"].startswith("wish672-")
    assert kw["min_waits"] == {**route_silver_blades.default_min_waits(),
                               **route_silver_blades.ACCEPT_MIN_WAITS}
    assert set(json.loads(capsys.readouterr().out.splitlines()[0])) == {
        "success", "error", "unguarded", "summary"}


def test_silver_blades_accept_expect_accepts_and_refutes(tmp_path, monkeypatch, capsys):
    _record_cli(monkeypatch)
    verdicts = iter(((True, "expect Guy id 1 at 47 minutes: accepts"),
                     (False, "expect Guy id 1 at 47 minutes: refutes")))
    monkeypatch.setattr(route_silver_blades, "expect_verdict",
                        lambda *args: next(verdicts))
    argv = ["accept", "--title", "ssb", "--manifest", str(tmp_path / "prepare.json"),
            "--guards", "guards.json", "--identity", "identity.json",
            "--journal-python", "python", "--audio-proof", "mute.json",
            "--expect", "Guy:1:47:5"]
    assert acceptance.main(argv) == 0
    assert capsys.readouterr().out.endswith("expect Guy id 1 at 47 minutes: accepts\n")
    assert acceptance.main(argv) == 1
    assert capsys.readouterr().out.endswith("expect Guy id 1 at 47 minutes: refutes\n")


def test_silver_blades_accept_requires_journal_before_guest_use(monkeypatch):
    monkeypatch.setattr(acceptance, "WinGuest", lambda: pytest.fail("guest created"))
    assert acceptance.main(["accept", "--title", "ssb", "--manifest", "m.json",
                            "--guards", "g.json", "--identity", "i.json",
                            "--audio-proof", "mute.json"]) == 2


def test_other_titles_refuse_silver_blades_only_options(monkeypatch):
    monkeypatch.setattr(acceptance, "WinGuest", lambda: pytest.fail("guest created"))
    assert acceptance.main(["prepare", "--title", "pool", "--run-id", "run",
                            "--source", "source.d64"]) == 2
    assert acceptance.main(["accept", "--title", "pool", "--manifest", "m.json",
                            "--guards", "g.json", "--identity", "i.json",
                            "--audio-proof", "mute.json", "--attempt", "a",
                            "--journal-python", "python"]) == 2


def test_silver_blades_reload_refuses_before_guest_use(monkeypatch):
    monkeypatch.setattr(acceptance, "WinGuest", lambda: pytest.fail("guest created"))
    assert acceptance.main(["reload", "--title", "ssb", "--manifest", "m.json",
                            "--guards", "g.json", "--identity", "i.json",
                            "--audio-proof", "mute.json"]) == 2


def test_the_answerer_runs_in_its_own_interpreter_and_only_its_last_line_is_kept(tmp_path):
    script = tmp_path / "fake_answerer.py"
    script.write_text(
        "import sys, pathlib\n"
        f"pathlib.Path({str(tmp_path / 'argv.txt')!r}).write_text(' '.join(sys.argv[1:]))\n"
        "print('noise')\nprint('answered')\n")
    code, line = route_silver_blades.run_journal_answer(
        sys.executable, "wish672-x", tmp_path / "side-a.adf", 60, script=script)
    assert (code, line) == (0, "answered")
    assert (tmp_path / "argv.txt").read_text() == (
        f"--holder wish672-x --adf {tmp_path / 'side-a.adf'}")


def test_the_answerer_exit_code_and_a_timeout_are_reported(tmp_path):
    script = tmp_path / "fake_answerer.py"
    script.write_text("print('no challenge on screen')\nraise SystemExit(1)\n")
    assert route_silver_blades.run_journal_answer(
        sys.executable, "h", tmp_path / "a", 60, script=script) == (
        1, "no challenge on screen")
    script.write_text("import time\ntime.sleep(60)\n")
    with pytest.raises(winuaesession.RouteError, match="exceeded"):
        route_silver_blades.run_journal_answer(sys.executable, "h", tmp_path / "a", 1, script=script)


def _after(n, name):
    """A rule that matches `name` from its n-th look on, so a wait polls n-1 times first."""
    looks = []

    def rule(path):
        if path.name != name:
            return False
        looks.append(1)
        return len(looks) >= n
    return rule


def _always(*names):
    return lambda path: path.name in names


def test_the_continue_screen_is_answered_at_most_once_per_wait(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    guard = MapGuard(on={"continue": _always("11-world.png"),
                         "world": lambda p: "world" in p.name and (
                             p.name != "11-world.png" or _wait11())})
    seen = []
    _wait11 = lambda: seen.append(1) or len(seen) >= 6  # noqa: E731
    guard.states.add("continue")
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard)
    assert len(seen) >= 6 and _keys(guest).count("RET") == 1
    assert result["success"] is True


def test_the_credits_are_left_at_most_once_per_wait(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    guard = MapGuard(on={"credits": _always("title.png"),
                         "title": _after(6, "title.png")})
    guard.states.add("credits")
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard)
    assert _keys(guest).count("ESC") == 1 and result["success"] is True


def test_the_journal_is_answered_at_most_once_per_wait(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    guest.answer = answer = Answer(guest)
    guard = MapGuard(on={"journal": _always("10-journal.png", "16-exit_game.png"),
                         "exit_game": _after(6, "16-exit_game.png")})
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard, answer=answer)
    assert len(answer.calls) == 2 and result["success"] is True  # the route's and the question's


def test_an_unguarded_state_acts_once_per_screen_whatever_the_guards_keep_saying(
        tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    guest.answer = answer = Answer(guest)
    guard = MapGuard(set(MapGuard.ALL) - {"exit_game"},
                     on={"continue": _always("16-exit_game.png"),
                         "journal": _always("10-journal.png", "16-exit_game.png")})
    guard.states.add("continue")
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard, answer=answer)
    assert _keys(guest).count("RET") == 1 and len(answer.calls) == 2
    assert result["unguarded"] == ["exit_game"]


@pytest.mark.parametrize("facing", [0, 1, 2, 3])
def test_two_squares_are_judged_along_every_facing(facing):
    dx, dy = acceptance.geo.STEP[facing]
    base = dict(BEFORE, x=5, y=5, facing=facing)

    def at(squares, **over):
        return _reading(x=(5 + dx * squares) % 16, y=(5 + dy * squares) % 16,
                        facing=facing) | over

    ok = acceptance.walk_verdict(base, at(0), at(2), 2)
    assert ok["d_ok"] is True and ok["squares_moved"] == 2
    for squares in (1, 3):
        assert acceptance.walk_verdict(base, at(0), at(squares), 2)["d_ok"] is False
    blocked = acceptance.walk_verdict(base, at(0), at(0), 2)
    assert blocked["d_ok"] is False and blocked["verdicts"][1] == "slot D: did not move"
    assert blocked["walk_blocked"] is True
    assert ok["walk_blocked"] is False  # moving as expected is never a wall block
    edge = dict(base, x=15 if dx else 5, y=15 if dy else 5)
    wrapped = acceptance.walk_verdict(
        edge, _reading(x=edge["x"], y=edge["y"], facing=facing),
        _reading(x=(edge["x"] + dx * 2) % 16, y=(edge["y"] + dy * 2) % 16, facing=facing), 2)
    assert wrapped["d_ok"] is True


def test_an_injected_answerer_needs_no_journal_interpreter_for_the_preflight(
        tmp_path, clock, readings):
    guest, result = _accept(tmp_path, clock, journal_python=None, preflight=None)
    assert result["success"] is True


class DrawGuest(AcceptGuest):
    """A camp save asks its question at once, before the slot picker, when the helper has staged one."""

    def __init__(self, clock, helper, *, questions=None):
        super().__init__(clock)
        self.helper, self.pending, self.questions, self.log = helper, False, questions, []
        self.pressed_while_asked = []

    def press(self, holder, key, timeout=None):
        if self.pending:
            self.pressed_while_asked.append(key)
        super().press(holder, key, timeout)
        if key == "S" and self.helper.calls:
            self.log.append("S")
        # The menu's own save (`S` before slot B is written) never asks.
        if key == "S" and self.written_b and self.helper.armed and self.questions != 0:
            self.pending, self.helper.armed = True, False
            self.questions = None if self.questions is None else self.questions - 1


def _draws(tmp_path, clock, monkeypatch, draws, *, questions=None, memory=None, refuse_at=None,
           lane_check=None, helper_args=None, answer_seconds=0.0, picker_seen=True,
           seed=None, reader=None, **kw):
    memory = memory or FakeGameMemory()
    log = []
    if seed is not None:
        seed.log = log
        seed.memory = memory
        monkeypatch.setattr(acceptance, "_load_drawseed", lambda: seed)
    helper = fake_stage_helper(memory, log, refuse_at=refuse_at, **(helper_args or {}))
    monkeypatch.setattr(route_silver_blades, "_load_savecount", lambda: helper)
    guest = DrawGuest(clock, helper, questions=questions)
    guest.log = log
    asked = lambda p: p.stem.endswith("camp_save_picker") and guest.pending  # noqa: E731
    guard = MapGuard(on={"journal": lambda p: p.name == "10-journal.png" or asked(p),
                         "camp_save_picker": lambda p: (p.stem.endswith("camp_save_picker")
                                                        and not guest.pending
                                                        and (picker_seen or not helper.calls)),
                         "exit_game": lambda p: p.stem.endswith("exit_game") and not guest.pending})

    class Answered(Answer):
        def __call__(self, holder, adf, timeout):
            guest.pending = False
            clock.now += answer_seconds
            if reader is not None and helper.calls and reader_values:
                with (reader / "tally.jsonl").open("a") as tally:
                    tally.write(json.dumps({"record": reader_values.pop(0)}) + "\n")
            return super().__call__(holder, adf, timeout)

    reader_values = list(reader_values_in) if (reader_values_in := kw.pop("reader_values", None)) else []
    guest.answer = answer = Answered(guest)
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard, answer=answer,
                        rulebook_draws=draws, target=memory,
                        lane_check=lane_check or (lambda: log.append("lane")), **kw)
    return types.SimpleNamespace(guest=guest, memory=memory, helper=helper, answer=answer,
                                 result=result, log=log)


def test_each_further_draw_stages_the_question_and_camp_saves_again(
        tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 3)
    assert _keys(run.guest) == KEYS + ["S", "D", "N"] * 2
    assert [c[:2] for c in run.helper.calls] == [(run.memory.read, run.memory.write)] * 2
    assert {c[2] for c in run.helper.calls} == {run.memory.BASE + A4_BIAS}
    assert len(run.answer.calls) == 4  # BEGIN's, then one per camp save
    assert run.result["rulebook"] == [
        {"draw": n, "asked": True, "answer": "answered", "exit_game": True} for n in (2, 3)]
    assert run.result["error"] == "" and run.result["success"] is True


def test_a_slow_answer_does_not_use_up_the_wait_for_the_screen_after_it(
        tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 2, answer_seconds=acceptance.GUARD_LIMIT + 10,
                 deadline_seconds=3600)
    assert run.result["error"] == "" and run.result["success"] is True


def test_a_draw_whose_wait_raises_after_the_answer_still_records_it(
        tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 2, picker_seen=False)
    assert "was not recognized" in run.result["error"]
    assert run.result["rulebook"] == [
        {"draw": 2, "asked": True, "answer": "answered", "exit_game": False}]
    drawn = [e for e in _events(tmp_path) if e["event"] == "draw"]
    assert drawn[0]["asked"] is True and drawn[0]["answer"] == "answered"


def test_the_question_is_answered_after_s_and_before_any_slot_letter(
        tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 2)
    assert run.guest.pressed_while_asked == []
    keys = _keys(run.guest)
    at_answer = run.answer.calls[-1][0]  # keys pressed when the camp save's question was answered
    assert keys[at_answer - 1] == "S" and keys[at_answer] == "D"
    assert run.result["success"] is True


def test_staging_comes_after_a_lane_check_and_before_s(tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 3)
    assert run.log == ["lane", "stage", "S"] * 2
    assert [c[0] for c in run.helper.calls] == [run.memory.read] * 2


def test_each_draw_goes_in_the_run_log_once(tmp_path, clock, readings, monkeypatch):
    _draws(tmp_path, clock, monkeypatch, 3)
    drawn = [e for e in _events(tmp_path) if e["event"] == "draw"]
    assert [e["draw"] for e in drawn] == [2, 3] and all(e["asked"] for e in drawn)


def test_the_game_is_located_once_when_the_world_is_reached(tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 3)
    assert run.memory.locates == 1


def test_a_game_that_cannot_be_located_stops_before_the_first_camp_save(
        tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 3, memory=FakeGameMemory(error=GuestError("gone")))
    assert _keys(run.guest) == KEYS[:10] and run.helper.calls == []
    assert "gone" in run.result["error"] and run.result["success"] is False


def test_one_draw_is_the_route_alone_and_needs_no_target(tmp_path, clock, readings):
    guest, result = _accept(tmp_path, clock, rulebook_draws=1)
    assert _keys(guest) == KEYS and "rulebook" not in result and result["success"] is True


def test_a_draw_that_reaches_exit_game_with_no_question_fails_the_run(
        tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 3, questions=1)
    assert _keys(run.guest) == KEYS + ["S", "D"]
    assert "draw 2 reached exit_game with no question" in run.result["error"]
    assert run.result["rulebook"][-1]["asked"] is False and run.result["success"] is False


def test_a_refusal_by_the_helper_stops_before_s_and_its_type_is_logged(
        tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 3, refuse_at=2)
    assert _keys(run.guest) == KEYS + ["S", "D", "N"]
    assert run.result["error"] == "RouteError: draw 3: SaveCountError"
    refused = [e for e in _events(tmp_path) if e["event"] == "draw_error"]
    assert [(e["draw"], e["error"]) for e in refused] == [(3, "SaveCountError")]
    assert run.result["success"] is False


def test_a_helper_message_never_reaches_the_log_or_the_result(
        tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 3, refuse_at=1,
                 helper_args={"message": "private-detail"})
    assert "private-detail" not in (tmp_path / "recon1" / "run.jsonl").read_text()
    assert "private-detail" not in json.dumps(run.result, default=str)
    assert "private-detail" not in (tmp_path / "recon1" / "summary.json").read_text()


def test_any_other_failure_out_of_the_helper_is_logged_by_type_and_raised(
        tmp_path, clock, readings, monkeypatch):
    run = _draws(tmp_path, clock, monkeypatch, 3,
                 helper_args={"raises": GuestError("private-detail")})
    failed = [e for e in _events(tmp_path) if e["event"] == "draw_error"]
    assert [(e["draw"], e["error"]) for e in failed] == [(2, "GuestError")]
    assert _keys(run.guest) == KEYS and run.result["success"] is False


def test_without_the_lane_claim_nothing_is_staged(tmp_path, clock, readings, monkeypatch):
    def unclaimed():
        raise GuestError("no claim")

    run = _draws(tmp_path, clock, monkeypatch, 3, lane_check=unclaimed)
    assert run.helper.calls == [] and _keys(run.guest) == KEYS
    assert "lane claim was not confirmed" in run.result["error"]


def test_draws_are_refused_before_the_claim_without_what_they_need(
        tmp_path, clock, readings, monkeypatch):
    guest = AcceptGuest(clock)
    with pytest.raises(acceptance.RouteError, match="memory target"):
        _accept(tmp_path, clock, guest=guest, rulebook_draws=2, lane_check=lambda: None)
    with pytest.raises(acceptance.RouteError, match="lane check"):
        _accept(tmp_path, clock, guest=guest, rulebook_draws=2, target=FakeGameMemory())
    monkeypatch.setattr(route_silver_blades, "_load_savecount", lambda: object())
    with pytest.raises(acceptance.RouteError, match="lacks stage_live"):
        _accept(tmp_path, clock, guest=guest, rulebook_draws=2, target=FakeGameMemory(),
                lane_check=lambda: None)
    assert guest.calls == []


def test_draws_that_cannot_fit_the_deadline_are_refused_before_the_claim(
        tmp_path, clock, readings, monkeypatch):
    monkeypatch.setattr(route_silver_blades, "_load_savecount",
                        lambda: fake_stage_helper(FakeGameMemory(), []))
    guest = AcceptGuest(clock)
    with pytest.raises(acceptance.RouteError, match=r"15 rulebook draws need about \d+s"):
        _accept(tmp_path, clock, guest=guest, rulebook_draws=15, target=FakeGameMemory(),
                lane_check=lambda: None, deadline_seconds=600)
    assert guest.calls == []
    run = _draws(tmp_path, clock, monkeypatch, 3, deadline_seconds=1800)
    assert run.result["success"] is True


@pytest.mark.parametrize("draws", [0, 16, -1])
def test_a_draw_count_outside_one_to_fifteen_is_refused(tmp_path, clock, readings, draws):
    with pytest.raises(acceptance.RouteError, match="1 to 15"):
        _accept(tmp_path, clock, rulebook_draws=draws)


def test_an_answered_screen_is_kept_under_its_own_name_in_a_draw_run(
        tmp_path, clock, readings, monkeypatch):
    _draws(tmp_path, clock, monkeypatch, 2)
    shots = tmp_path / "recon1" / "shots"
    kept = shots / "15-camp_save_picker-journal-1.png"
    assert kept.read_bytes().startswith(b"frame")
    assert kept.with_name("15-camp_save_picker-journal-1.raw.png").read_bytes().startswith(b"grab")
    assert (shots / "18-camp_save_picker-journal-1.png").exists()


def test_a_run_without_draws_keeps_no_interstitial_copies(tmp_path, clock, readings):
    guest = AcceptGuest(clock)
    guest.answer = answer = Answer(guest)
    asked = lambda p: p.name == "16-exit_game.png" and len(answer.calls) < 2  # noqa: E731
    guard = MapGuard(on={"journal": lambda p: p.name == "10-journal.png" or asked(p),
                         "exit_game": lambda p: p.name == "16-exit_game.png" and not asked(p)})
    _, result = _accept(tmp_path, clock, guest=guest, guard=guard, answer=answer)
    assert len(answer.calls) == 2 and result["success"] is True
    assert not list((tmp_path / "recon1" / "shots").glob("*-journal-*"))


def test_a_failed_copy_of_a_kept_screen_is_logged_and_the_run_goes_on(
        tmp_path, clock, readings, monkeypatch):
    def refuse(*args):
        raise OSError("disk full")

    monkeypatch.setattr(acceptance.shutil, "copyfile", refuse)
    run = _draws(tmp_path, clock, monkeypatch, 2)
    assert run.result["success"] is True
    errors = [e for e in _events(tmp_path) if e["event"] == "interstitial_keep_error"]
    assert errors and "disk full" in errors[0]["error"]


def test_silver_blades_accept_forwards_the_draws_and_a_memory_target(monkeypatch):
    seen, _ = _record_cli(monkeypatch)
    argv = ["accept", "--title", "ssb", "--manifest", "m.json", "--guards", "g.json",
            "--identity", "i.json", "--journal-python", "python", "--audio-proof", "mute.json"]
    assert acceptance.main([*argv, "--rulebook-draws", "3"]) == 0
    kw = seen[0][1]
    assert kw["rulebook_draws"] == 3 and kw["target"].layout.executable == "/Secret"
    assert callable(kw["lane_check"])
    assert acceptance.main([*argv, "--rulebook-draws", "1"]) == 0
    assert seen[1][1]["rulebook_draws"] == 1 and "target" not in seen[1][1]
    assert acceptance.main(argv) == 0 and "rulebook_draws" not in seen[2][1]


def test_rulebook_draws_are_only_for_silver_blades_accept(monkeypatch, capsys):
    _record_cli(monkeypatch)
    common = ["--manifest", "m.json", "--guards", "g.json", "--identity", "i.json",
              "--audio-proof", "mute.json", "--attempt", "a1"]
    assert acceptance.main(["accept", "--title", "pool", *common, "--rulebook-draws", "2"]) == 2
    assert acceptance.main(["accept", "--title", "ssb", *common, "--journal-python", "py",
                            "--published-disk-one", "--rulebook-draws", "2"]) == 2
    assert capsys.readouterr().err.count("--rulebook-draws requires") == 2


def test_prepare_passes_the_save_count_to_the_silver_blades_route(
        tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(route_silver_blades, "prepare",
                        lambda *a, **kw: seen.append((a, kw)) or tmp_path / "prepare.json")
    argv = ["prepare", "--title", "ssb", "--run-id", "r", "--source", "s.d64"]
    assert acceptance.main([*argv, "--save-count", "5"]) == 0
    assert seen[0][1]["save_count"] == 5
    assert acceptance.main(argv) == 0 and "save_count" not in seen[1][1]


def test_the_save_count_is_only_for_silver_blades_prepare(capsys):
    assert acceptance.main(["prepare", "--title", "pool", "--run-id", "r",
                            "--save-count", "5"]) == 2
    assert "--save-count" in capsys.readouterr().err


class FakeDrawSeed:
    """A fake private `drawseed`: `stage_draw` remembers the record, `drawn` reports it after `shift`."""

    class DrawSeedError(ValueError):
        pass

    def __init__(self, shift=0, refuse=False, raises=None, drawn_raises=None, index_raises=None):
        self.shift, self.refuse, self.raises, self.drawn_raises = shift, refuse, raises, drawn_raises
        self.index_raises = index_raises
        self.staged, self.calls, self.log = [], [], []

    def stage_draw(self, read, write, a4, k):
        self.calls.append((read, write, a4, k))
        self.log.append(f"seed{k}")
        if self.raises is not None:
            raise self.raises
        if self.refuse:
            raise self.DrawSeedError("refused by the helper")
        self.staged.append(k)

    def reader_index(self, k, table=None):
        if self.index_raises is not None:
            raise self.index_raises
        return 1000 + k

    def drawn(self, read, a4):
        if self.drawn_raises is not None:
            raise self.drawn_raises
        return self.staged[-1] + self.shift


def _seeded(tmp_path, clock, monkeypatch, records, *, seed=None, reader_values=None, **kw):
    seed = seed or FakeDrawSeed()
    (tmp_path / "keep").mkdir()
    monkeypatch.setenv(route_silver_blades.KEEP_ENV, str(tmp_path / "keep"))
    run = _draws(tmp_path, clock, monkeypatch, len(records) + 1, seed=seed,
                 rulebook_records=records, reader=tmp_path / "keep",
                 reader_values=reader_values, **kw)
    return seed, run


def test_each_staged_record_is_seeded_after_the_question_and_before_s(
        tmp_path, clock, readings, monkeypatch):
    seed, run = _seeded(tmp_path, clock, monkeypatch, [3, 7], reader_values=[1003, 1007])
    assert run.log == ["lane", "stage", "seed3", "S", "lane", "stage", "seed7", "S"]
    assert [c[3] for c in seed.calls] == [3, 7]
    assert [c[:2] for c in seed.calls] == [(run.memory.read, run.memory.write)] * 2
    assert {c[2] for c in seed.calls} == {run.memory.BASE + A4_BIAS}
    assert run.result["rulebook"] == [
        {"draw": 2, "asked": True, "answer": "answered", "exit_game": True,
         "staged": 3, "drawn": 3, "reader": 1003},
        {"draw": 3, "asked": True, "answer": "answered", "exit_game": True,
         "staged": 7, "drawn": 7, "reader": 1007}]
    assert run.result["success"] is True
    logged = [e for e in _events(tmp_path) if e["event"] == "draw"]
    assert [e["drawn"] for e in logged] == [3, 7]


def test_a_draw_that_is_not_the_staged_record_fails_the_run_naming_no_value(
        tmp_path, clock, readings, monkeypatch):
    _, run = _seeded(tmp_path, clock, monkeypatch, [3, 7], seed=FakeDrawSeed(shift=1),
                     reader_values=[1004, 1008])
    assert run.result["success"] is False
    assert "not the staged record" in run.result["error"]
    assert not any(ch.isdigit() for ch in run.result["error"].split("draw 2")[-1])


def test_a_reader_index_other_than_the_helpers_for_the_drawn_record_fails_the_run(
        tmp_path, clock, readings, monkeypatch):
    _, run = _seeded(tmp_path, clock, monkeypatch, [3, 7], reader_values=[1003, 1008])
    assert run.result["success"] is False and "reader disagrees" in run.result["error"]
    assert run.result["rulebook"][1]["reader"] == 1008


def test_a_staged_draw_the_reader_kept_nothing_for_fails_the_run(
        tmp_path, clock, readings, monkeypatch):
    _, run = _seeded(tmp_path, clock, monkeypatch, [3], reader_values=[])
    assert run.result["success"] is False and "no single capture" in run.result["error"]
    assert run.result["rulebook"][0]["reader"] is None


def test_records_are_refused_before_the_claim_without_the_keep_variable(
        tmp_path, clock, readings, monkeypatch):
    monkeypatch.delenv(route_silver_blades.KEEP_ENV, raising=False)
    monkeypatch.setattr(route_silver_blades, "_load_savecount",
                        lambda: fake_stage_helper(FakeGameMemory(), []))
    guest = AcceptGuest(clock)
    with pytest.raises(acceptance.RouteError, match="KEEP|JOURNAL_KEEP"):
        _accept(tmp_path, clock, guest=guest, rulebook_draws=2, rulebook_records=[1],
                target=FakeGameMemory(), lane_check=lambda: None, deadline_seconds=3600)
    assert guest.calls == []


def test_the_helpers_own_refusal_stops_the_draw_with_its_type_only(
        tmp_path, clock, readings, monkeypatch):
    _, run = _seeded(tmp_path, clock, monkeypatch, [3], seed=FakeDrawSeed(refuse=True))
    assert run.result["error"].endswith("stage_draw failed: DrawSeedError")
    assert "refused by the helper" not in run.result["error"]


@pytest.mark.parametrize("where", ["raises", "drawn_raises", "index_raises"])
def test_any_helper_exception_reaches_the_error_as_its_type_only(
        tmp_path, clock, readings, monkeypatch, where):
    _, run = _seeded(tmp_path, clock, monkeypatch, [3], seed=FakeDrawSeed(**{where: KeyError("secret")}),
                     reader_values=[1003])
    assert run.result["success"] is False
    assert "KeyError" in run.result["error"] and "secret" not in run.result["error"]
    assert "secret" not in json.dumps(_events(tmp_path))


def test_records_are_refused_before_the_claim_when_they_cannot_be_used(
        tmp_path, clock, readings, monkeypatch):
    guest = AcceptGuest(clock)
    monkeypatch.setenv(route_silver_blades.KEEP_ENV, str(tmp_path))
    monkeypatch.setattr(route_silver_blades, "_load_savecount",
                        lambda: fake_stage_helper(FakeGameMemory(), []))
    kw = {"guest": guest, "target": FakeGameMemory(), "lane_check": lambda: None,
          "deadline_seconds": 3600}
    with pytest.raises(acceptance.RouteError, match="one number per further draw"):
        _accept(tmp_path, clock, rulebook_draws=3, rulebook_records=[1], **kw)
    with pytest.raises(acceptance.RouteError, match="need rulebook draws"):
        _accept(tmp_path, clock, rulebook_records=[1], **kw)
    with pytest.raises(acceptance.RouteError, match="more than one draw"):
        _accept(tmp_path, clock, rulebook_draws=1, rulebook_records=[], **kw)
    monkeypatch.setattr(acceptance, "_load_drawseed", lambda: object())
    with pytest.raises(acceptance.RouteError, match="lacks stage_draw"):
        _accept(tmp_path, clock, rulebook_draws=2, rulebook_records=[1], **kw)
    monkeypatch.setattr(acceptance, "_load_drawseed",
                        lambda: types.SimpleNamespace(stage_draw=1, drawn=1, DrawSeedError=1))
    with pytest.raises(acceptance.RouteError, match="reader_index"):
        _accept(tmp_path, clock, rulebook_draws=2, rulebook_records=[1], **kw)
    assert guest.calls == []


def test_a_missing_private_drawseed_is_refused_naming_its_path(monkeypatch, tmp_path):
    monkeypatch.setenv(acceptance.amigabladesjournal.ENV, str(tmp_path))
    with pytest.raises(acceptance.RouteError, match="drawseed.py is missing"):
        acceptance._load_drawseed()


def test_silver_blades_accept_forwards_the_records(monkeypatch):
    seen, _ = _record_cli(monkeypatch)
    argv = ["accept", "--title", "ssb", "--manifest", "m.json", "--guards", "g.json",
            "--identity", "i.json", "--journal-python", "python", "--audio-proof", "mute.json"]
    assert acceptance.main([*argv, "--rulebook-draws", "3", "--rulebook-records", "3,7"]) == 0
    assert seen[0][1]["rulebook_records"] == [3, 7]
    assert acceptance.main([*argv, "--rulebook-draws", "3"]) == 0
    assert "rulebook_records" not in seen[1][1]


ISSUE = "#661 (a C64 party under a running spell)"


def _staged_manifest(tmp_path):
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text())
    staged = tmp_path / "staged.d64"
    staged.write_bytes(b"staged c64 source")
    data["source"] = {"path": str(staged), "sha256": _sha(staged)}
    data["staged_from"] = {"path": "/join.d64", "sha256": "a" * 64}
    data["active_rows"] = [[63, 1, 0, 0x2F, 5]]
    data["stage"] = {"letter": "C"}
    manifest.write_text(json.dumps(data))
    return manifest


@pytest.fixture
def specimen_tree(tmp_path, monkeypatch):
    from tests.registry.test_specimens import _unlock
    from tools.registry import specimens
    root = tmp_path / "specimens"
    monkeypatch.setattr(specimens, "tree_root", lambda: root)
    yield root
    if root.is_dir():
        _unlock(root)


def test_a_staged_accept_registers_its_fetched_disk_and_names_the_staged_source(
        tmp_path, clock, readings, specimen_tree):
    from tools.registry import specimens
    _, result = _accept(tmp_path, clock, manifest=_staged_manifest(tmp_path),
                        preserve_specimen=True, specimen_issue=ISSUE)
    assert result["success"] is True, result.get("specimen_error")
    fetched = tmp_path / "recon1" / "fetched-df0.adf"
    assert result["specimen"]["sha256"] == _sha(fetched)
    assert specimens.check_specimens(specimen_tree) == []
    provenance = specimens.read_provenance(pathlib.Path(result["specimen"]["provenance"]))
    assert provenance["issue"] == ISSUE
    what = provenance["what"]
    assert "The game wrote slots B and D." in what
    assert "Wish-staged C64 source" in what and "a" * 64 in what and "/join.d64" in what
    assert str(tmp_path / "staged.d64") in what and _sha(tmp_path / "staged.d64") in what
    assert "[[63, 1, 0, 47, 5]]" in what and '{"letter": "C"}' in what


def test_a_staged_accept_that_fails_registers_nothing(
        tmp_path, clock, readings, specimen_tree):
    readings["D"] = _reading(y=5)
    _, result = _accept(tmp_path, clock, manifest=_staged_manifest(tmp_path),
                        preserve_specimen=True, specimen_issue=ISSUE)
    assert result["success"] is False and "specimen" not in result
    assert not specimen_tree.exists() or list(specimen_tree.rglob("WISH-SPEC-*")) == []


def test_an_unstaged_silver_blades_accept_still_refuses_preservation(tmp_path, clock, specimen_tree):
    guest = AcceptGuest(clock)
    with pytest.raises(winuaesession.RouteError, match="published disk-one or substituted"):
        _accept(tmp_path, clock, guest=guest, preserve_specimen=True, specimen_issue=ISSUE)
    assert guest.calls == []


def test_a_staged_accept_needs_a_cited_issue_before_any_guest_call(tmp_path, clock):
    guest = AcceptGuest(clock)
    with pytest.raises(winuaesession.RouteError, match="--specimen-issue"):
        _accept(tmp_path, clock, guest=guest, manifest=_staged_manifest(tmp_path),
                preserve_specimen=True, specimen_issue="661")
    assert guest.calls == []
