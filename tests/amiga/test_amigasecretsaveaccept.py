"""The accept mode of the Silver Blades driver: route, guards, interstitials, verdicts and evidence."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys

import pytest

from goldbox.amiga_adf import AmigaDisk
from tests.amiga import test_amigasecretsavemeasure as measure
from tests.amiga.test_amigasecretsave import _audio_proof, _sha
from tests.amiga.test_amigasecretsavemeasure import ScreenGuest, _keys, _menu_manifest
from tools.amiga import amigasecretsave as drive

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
    monkeypatch.setattr(drive, "_slot_reading", lambda fetched, letter: by_letter[letter])
    return by_letter


def _accept(tmp_path, clock, *, guest=None, guard=None, identity=None, answer=None,
            manifest=None, **kw):
    guest = guest or AcceptGuest(clock)
    guest.answer = answer or Answer(guest)
    kw.setdefault("preflight", lambda python: None)
    kw.setdefault("journal_python", "python-with-numpy")
    result = drive.run_recon(
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
    assert [(k, s, kind) for k, s, kind in drive.ACCEPT_ROUTE] == [
        ("P", "party_menu", "key"), ("L", "load_picker", "key"),
        ("C", "loaded_menu", "key"), ("V", "sheet", "key"), ("I", "items", "key"),
        ("E", "sheet", "key"), ("E", "loaded_menu", "key"), ("S", "save_picker", "key"),
        ("B", "loaded_menu", "write"), ("B", "journal", "key"),
        (None, "world", "answer"), ("NP8", "world", "move"), ("NP8", "world", "move"),
        ("E", "camp", "key"), ("S", "camp_save_picker", "key"),
        ("D", "exit_game", "write"), ("N", "camp", "key")]
    assert drive.MENU_SAVE_LETTER == "B" and drive.CAMP_SAVE_LETTER == "D"


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
    verdict = drive.walk_verdict(before, _reading(y=15), _reading(y=1), 2)
    assert verdict["d_ok"] is True and verdict["squares_moved"] == 2
    assert verdict["verdicts"][1] == "slot D: moved 2 squares from 3,15 to 3,1"


def test_a_missing_or_undecodable_slot_is_named():
    verdict = drive.walk_verdict(BEFORE, {"missing": True, "sha256": None},
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
    with pytest.raises(drive.RouteError, match="lacks .*sheet"):
        _accept(tmp_path, clock, guest=guest,
                guard=MapGuard(set(MapGuard.ALL) - {"sheet"}))
    assert guest.calls == []


def test_accept_refuses_before_the_claim_without_identity(tmp_path, clock):
    guest = AcceptGuest(clock)
    with pytest.raises(drive.RouteError, match="identity map lacks"):
        drive.run_recon(_manifest(tmp_path), guest=guest, guard=MapGuard(),
                        holder="wish672-test", audio_proof=_audio_proof(tmp_path),
                        accept=True, answer=lambda *a: (0, "answered"),
                        identity=None)
    assert guest.calls == []


def test_accept_refuses_before_the_claim_without_a_journal_interpreter(tmp_path, clock):
    guest = AcceptGuest(clock)
    with pytest.raises(drive.RouteError, match="journal interpreter"):
        _accept(tmp_path, clock, guest=guest,
                journal_python=str(tmp_path / "no-such-python"), preflight=drive.journal_preflight)
    assert guest.calls == []


def test_accept_refuses_a_manifest_without_the_boot_disk_for_the_answerer(tmp_path, clock):
    manifest = _manifest(tmp_path)
    data = json.loads(manifest.read_text())
    del data["boot_source"]
    manifest.write_text(json.dumps(data))
    guest = AcceptGuest(clock)
    with pytest.raises(drive.RouteError, match="boot_source"):
        _accept(tmp_path, clock, guest=guest, manifest=manifest)
    assert guest.calls == []


def test_the_preflight_wants_the_imports_and_the_private_tables(tmp_path, monkeypatch):
    ran = []

    def run(argv, **kw):
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(drive.subprocess, "run", run)
    monkeypatch.setattr(drive.amigabladesjournal, "wheel_repo", lambda: tmp_path)
    with pytest.raises(drive.RouteError, match="not a directory"):
        drive.journal_preflight("py")
    (tmp_path / "ssb" / "analysis").mkdir(parents=True)
    drive.journal_preflight("py")
    assert ran[-1] == ["py", "-c", "import numpy, PIL"]
    monkeypatch.setattr(drive.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"", b""))
    with pytest.raises(drive.RouteError, match="cannot import numpy"):
        drive.journal_preflight("py")


def test_a_save_letter_that_is_a_prepared_slot_is_refused(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(drive, "MENU_SAVE_LETTER", drive.SLOT_LETTER)
    guest = AcceptGuest(clock)
    with pytest.raises(drive.RouteError, match="would overwrite"):
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
    drive.run_recon(_manifest(other), guest=recon_guest, guard=guard_for(recon_guest),
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
    assert gaps == [drive.GUARD_POLL] * 3


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
                       min_waits={**drive.default_min_waits(), **drive.ACCEPT_MIN_WAITS})
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
    guest = AcceptGuest(clock, raises=(3, drive.Terminated("signal 15")))
    guest, result = _accept(tmp_path, clock, guest=guest)
    assert [c[0] for c in guest.calls if c[0] in ("stop", "get", "release")] == [
        "stop", "get", "get", "release"]
    assert result["lost"].startswith("Terminated") and result["completed"] is False
    assert result["success"] is False
    assert _events(tmp_path)[-1]["event"] == "read" or any(
        e["event"] == "lost" for e in _events(tmp_path))
    summary = json.loads((tmp_path / "recon1" / "summary.json").read_text())
    assert summary["lost"] == result["lost"]


needs_posix_signals = pytest.mark.skipif(
    not hasattr(signal, "pthread_sigmask"), reason="this platform has no POSIX signals")


@needs_posix_signals
def test_the_installed_handler_raises_terminated_and_is_restored():
    old = signal.getsignal(signal.SIGTERM)
    with drive.terminating():
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not old
        with pytest.raises(drive.Terminated):
            handler(signal.SIGTERM, None)
        with pytest.raises(drive.Terminated):
            os.kill(os.getpid(), signal.SIGTERM)
    assert signal.getsignal(signal.SIGTERM) is old


def _main(tmp_path, clock, monkeypatch, guest, capsys):
    manifest = _manifest(tmp_path)
    guest.answer = Answer(guest)
    monkeypatch.setattr(drive, "WinGuest", lambda: guest)
    monkeypatch.setattr(drive, "PixelGuards", lambda path: MapGuard())
    monkeypatch.setattr(drive, "journal_preflight", lambda python: None)
    monkeypatch.setattr(drive, "run_journal_answer",
                        lambda python, holder, adf, timeout: guest.answer(holder, adf, timeout))
    argv = ["accept", "--manifest", str(manifest), "--guards", "g.json",
            "--identity", "i.json", "--journal-python", "py",
            "--audio-proof", str(_audio_proof(tmp_path))]
    code = drive.main(argv)
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


def test_the_answerer_runs_in_its_own_interpreter_and_only_its_last_line_is_kept(tmp_path):
    script = tmp_path / "fake_answerer.py"
    script.write_text(
        "import sys, pathlib\n"
        f"pathlib.Path({str(tmp_path / 'argv.txt')!r}).write_text(' '.join(sys.argv[1:]))\n"
        "print('noise')\nprint('answered')\n")
    code, line = drive.run_journal_answer(
        sys.executable, "wish672-x", tmp_path / "side-a.adf", 60, script=script)
    assert (code, line) == (0, "answered")
    assert (tmp_path / "argv.txt").read_text() == (
        f"--holder wish672-x --adf {tmp_path / 'side-a.adf'}")


def test_the_answerer_exit_code_and_a_timeout_are_reported(tmp_path):
    script = tmp_path / "fake_answerer.py"
    script.write_text("print('no challenge on screen')\nraise SystemExit(1)\n")
    assert drive.run_journal_answer(sys.executable, "h", tmp_path / "a", 60, script=script) == (
        1, "no challenge on screen")
    script.write_text("import time\ntime.sleep(60)\n")
    with pytest.raises(drive.RouteError, match="exceeded"):
        drive.run_journal_answer(sys.executable, "h", tmp_path / "a", 1, script=script)
