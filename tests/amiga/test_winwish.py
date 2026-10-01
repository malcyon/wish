"""`tools/amiga/winwish.py`, which runs the frozen Windows Wish beside WinUAE, with fakes.

No VM, no `gh` and no network: the `winvm` and `gh` calls go through one function
that the tests replace, and the WinUAE lane is a recording stand-in, so what is
under test is the argument handling, the order of the steps and what each one
undoes when a later one fails.
"""

from __future__ import annotations

import base64
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import winvmguest, winwish  # noqa: E402
from tools.amiga.winuaesession import RouteError  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


class FakeRun:
    """Stands in for `winwish._run`: records argv, answers from a list of rules."""

    def __init__(self, rules=()):
        self.calls: list[list[str]] = []
        self.rules = list(rules)

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        for match, rc, out in self.rules:
            if match(argv):
                return rc, out
        return 0, "ok"

    def verbs(self):
        return [c[1] if c[0] == "winvm" else " ".join(c[:3]) for c in self.calls]


def _script(argv: list[str]) -> str:
    return argv[2]


class FakeLane:
    def __init__(self, fail_on: str | None = None, exc=RouteError):
        self.log: list[str] = []
        self.fail_on = fail_on
        self.exc = exc

    def _do(self, name, *args):
        self.log.append(name)
        if name == self.fail_on:
            raise self.exc(f"{name} failed")
        return f"ok {name}"

    def claim(self, holder, timeout):
        return self._do("claim")

    def start(self, holder, *drives, timeout):
        self.log.append("drives=" + ",".join(drives))
        return self._do("start")

    def stop(self, holder, timeout):
        return self._do("stop")

    def release(self, holder, timeout):
        return self._do("release")


def _mute(tmp_path, monkeypatch, good=True):
    proof = tmp_path / "mute.json"
    proof.write_text("{}")
    monkeypatch.setattr(winwish, "_mute_proof", lambda path: good)
    return str(proof)


# -- names and settings -------------------------------------------------------

def test_a_sha_is_checked_and_shortened():
    assert winwish.short_sha(SHA.upper()) == SHA[:12]
    for bad in ("", "xyz", "abc", SHA + "0", "--help"):
        with pytest.raises(winwish.WinwishError):
            winwish.short_sha(bad)


def test_a_short_sha_is_resolved_with_git_and_a_full_one_is_not():
    run = FakeRun([(lambda a: a[0] == "git", 0, SHA + "\n")])
    assert winwish.full_sha(winwish.Guest(run), SHA[:9]) == SHA
    assert run.calls[0][:3] == ["git", "rev-parse", "--verify"]
    run = FakeRun()
    assert winwish.full_sha(winwish.Guest(run), SHA.upper()) == SHA
    assert run.calls == []
    bad = FakeRun([(lambda a: a[0] == "git", 1, "")])
    with pytest.raises(winwish.WinwishError, match="cannot resolve"):
        winwish.full_sha(winwish.Guest(bad), SHA[:9])


def test_each_holder_has_its_own_task():
    assert winwish.task_name("a") != winwish.task_name("b")
    assert winwish.task_name("a") == "wish-run-a"


def test_a_holder_cannot_climb_out_of_its_folder():
    with pytest.raises(winwish.WinwishError):
        winwish.run_dir("..\\x")
    assert winwish.run_dir("pod-1") == r"C:\Amiga\wish\run-pod-1"


def test_the_environment_carries_the_flag_only_when_asked():
    on = winwish.environment(True, "h")
    off = winwish.environment(False, "h")
    assert on[winwish.FLAG] == "1" and on["WISH_DEBUG"] == "1"
    assert winwish.FLAG not in off and off["WISH_DEBUG"] == "1"
    assert on["APPDATA"] == r"C:\Amiga\wish\run-h\appdata"
    assert on["LOCALAPPDATA"] == r"C:\Amiga\wish\run-h\local"


def test_the_seeded_settings_turn_the_log_on_and_parse_as_json():
    assert json.loads(winwish.settings_json()) == {"diagnostics": True}


def test_the_log_folder_is_where_wish_writes_it():
    from wish import debuglog  # noqa: PLC0415
    assert winwish.log_dir("h").endswith(r"\appdata\wish\logs")
    assert debuglog.log_dir().name == "logs" and debuglog.log_dir().parent.name == "wish"


# -- the guest scripts --------------------------------------------------------

def test_start_script_writes_settings_without_a_bom_and_refuses_session_zero():
    script = winwish.start_script("h", winwish.environment(True, "h"))
    assert "UTF8Encoding $false" in script
    assert "automap.json" in script
    assert "session 0" in script
    assert "Register-ScheduledTask" in script and "-LogonType Interactive" in script
    inner = script.split("-EncodedCommand ")[1].split("'")[0]
    body = base64.b64decode(inner).decode("utf-16-le")
    assert "$env:WISH_EXPERIMENTAL_AMIGA_WINUAE = '1'" in body
    assert "$env:WISH_DEBUG = '1'" in body
    assert "Start-Process -Wait" in body
    assert "'wish-run-h'" in script
    for name in winwish.CLEARED:
        assert f"Remove-Item Env:{name}" in body
    assert f"Remove-Item Env:{winwish.FLAG}" not in body


def test_the_control_start_script_has_no_flag():
    script = winwish.start_script("h", winwish.environment(False, "h"))
    body = base64.b64decode(script.split("-EncodedCommand ")[1].split("'")[0]).decode("utf-16-le")
    assert f"Remove-Item Env:{winwish.FLAG}" in body
    assert f"$env:{winwish.FLAG}" not in body


def test_an_unreadable_process_path_fails_start_and_stop_instead_of_passing():
    for script in (winwish.start_script("h", winwish.environment(True, "h")),
                   winwish.stop_script("h")):
        assert "-not $_.Path" in script
        assert "cannot tell" in script


def test_stop_script_touches_only_this_holders_processes_and_removes_its_task():
    script = winwish.stop_script("h")
    assert r"C:\Amiga\wish\run-h" in script and "'wish-run-h'" in script
    assert "Unregister-ScheduledTask" in script
    assert "Stop-Process -Name" not in script


def test_window_capture_prints_the_wish_window():
    assert "PrintWindow" in winwish.window_capture(r"C:\x.png", "h")
    assert r"run-h" in winwish.window_capture(r"C:\x.png", "h")


def test_shot_script_default_is_unchanged_and_takes_a_capture():
    default = winvmguest.shot_script("abc")
    custom = winvmguest.shot_script("abc", capture=lambda out: "# marker")
    inner = lambda s: base64.b64decode(  # noqa: E731
        s.split("-EncodedCommand ")[1].split("'")[0]).decode("utf-16-le")
    assert "CopyFromScreen" in inner(default)
    assert inner(custom) == "# marker"


# -- fetching -----------------------------------------------------------------

RUNS = [
    {"databaseId": 1, "headSha": SHA, "conclusion": "failure", "createdAt": "2026-10-01T09:00:00Z"},
    {"databaseId": 2, "headSha": SHA, "conclusion": "success", "createdAt": "2026-10-01T10:00:00Z"},
    {"databaseId": 3, "headSha": SHA, "conclusion": "success", "createdAt": "2026-10-01T11:00:00Z"},
    {"databaseId": 4, "headSha": "f" * 40, "conclusion": "success", "createdAt": "2026-10-01T12:00:00Z"},
]


def test_pick_run_takes_the_newest_success_for_the_sha():
    assert winwish.pick_run(json.dumps(RUNS), SHA) == 3


def test_pick_run_says_what_to_start_when_there_is_none():
    with pytest.raises(winwish.WinwishError, match="gh workflow run release.yml"):
        winwish.pick_run(json.dumps(RUNS[:1]), SHA)
    with pytest.raises(winwish.WinwishError, match="JSON"):
        winwish.pick_run("not json", SHA)


def test_fetch_lists_by_commit_then_downloads_the_named_artifact(tmp_path):
    def download(argv):
        if argv[:3] == ["gh", "run", "download"]:
            (tmp_path / "wish-1-windows-x86_64.zip").write_bytes(b"PK")
        return argv

    run = FakeRun([(lambda a: a[1:3] == ["run", "list"], 0, json.dumps(RUNS))])
    inner = run.__call__

    def wrapped(argv, timeout):
        download(argv)
        return inner(argv, timeout)

    zipped = winwish.fetch(winwish.Guest(wrapped), SHA, tmp_path)
    assert zipped.name == "wish-1-windows-x86_64.zip"
    assert (tmp_path / "commit.txt").read_text().strip() == SHA
    listing, fetching = run.calls
    assert listing[listing.index("--commit") + 1] == SHA
    assert fetching[3] == "3" and fetching[fetching.index("--name") + 1] == "frozen-windows"


def test_fetch_can_run_twice_in_one_folder(tmp_path):
    def wrapped(argv, timeout):
        if argv[:3] == ["gh", "run", "download"]:
            (tmp_path / f"wish-{len(list(tmp_path.glob('*.zip')))}.zip").write_bytes(b"PK")
        if argv[1:3] == ["run", "list"]:
            return 0, json.dumps(RUNS)
        return 0, "ok"

    guest = winwish.Guest(wrapped)
    winwish.fetch(guest, SHA, tmp_path)
    assert winwish.fetch(guest, SHA, tmp_path).parent == tmp_path


def test_a_zip_fetched_for_another_commit_is_refused(tmp_path):
    zipped = tmp_path / "wish-1.zip"
    zipped.write_bytes(b"PK")
    (tmp_path / "commit.txt").write_text("f" * 40 + "\n")
    with pytest.raises(winwish.WinwishError, match="not " + SHA):
        winwish.check_zip_commit(zipped, SHA)
    (tmp_path / "commit.txt").write_text(SHA + "\n")
    winwish.check_zip_commit(zipped, SHA)
    (tmp_path / "commit.txt").unlink()
    winwish.check_zip_commit(zipped, SHA)


def test_fetch_rejects_a_sha_that_is_an_option():
    with pytest.raises(winwish.WinwishError):
        winwish.fetch(winwish.Guest(FakeRun()), "--repo=x")


# -- guest steps --------------------------------------------------------------

def test_start_requires_the_lane_before_touching_the_guest():
    run = FakeRun([(lambda a: a[1] == "lane", 1, "free")])
    with pytest.raises(winwish.WinwishError, match="does not hold"):
        winwish.start_wish(winwish.Guest(run), "h")
    assert run.verbs() == ["lane"]


def test_a_script_that_does_not_say_ok_is_an_error():
    run = FakeRun([(lambda a: a[1] == "ps", 1, "fail wish.exe in session 0")])
    with pytest.raises(winwish.WinwishError, match="session 0"):
        winwish.start_wish(winwish.Guest(run), "h")


def test_restart_stops_before_it_starts():
    run = FakeRun()
    winwish.restart_wish(winwish.Guest(run), "h")
    scripts = [c[2] for c in run.calls if c[1] == "ps"]
    assert "Stop-ScheduledTask" in scripts[0] and "Register-ScheduledTask" not in scripts[0]
    assert "Register-ScheduledTask" in scripts[1]


def test_stage_makes_the_folder_copies_and_unpacks_a_fresh_build_in_that_order(tmp_path):
    zipped = tmp_path / "wish-1.zip"
    zipped.write_bytes(b"PK")
    run = FakeRun()
    winwish.stage(winwish.Guest(run), "h", zipped)
    assert run.verbs() == ["ps", "put", "ps"]
    assert run.calls[1][3] == "C:/Amiga/wish/run-h/"
    script = run.calls[2][2]
    zip_sha = winwish.file_sha256(zipped)
    assert "Remove-Item -LiteralPath $b -Recurse" in script
    assert script.index("Remove-Item") < script.index("Expand-Archive")
    assert rf"C:\Amiga\wish\run-h\build\{zip_sha[:12]}" in script
    assert zip_sha in script


def test_shot_decodes_the_png_and_writes_it(tmp_path):
    png = winvmguest.PNG_SIGNATURE + b"data"
    reply = "\n".join([winvmguest.SHOT_BEGIN, base64.b64encode(png).decode(), winvmguest.SHOT_END])
    run = FakeRun([(lambda a: a[1] == "ps", 0, reply)])
    out = tmp_path / "s" / "wish.png"
    assert winwish.shot(winwish.Guest(run), "h", "wish", out) == len(png)
    assert out.read_bytes() == png


def test_shot_reports_a_guest_that_returned_no_screenshot(tmp_path):
    run = FakeRun([(lambda a: a[1] == "ps", 0, "fail no screenshot after 20s")])
    with pytest.raises(winwish.WinwishError, match="no screenshot"):
        winwish.shot(winwish.Guest(run), "h", "desktop", tmp_path / "x.png")


def test_log_copies_the_holders_folder_and_insists_on_a_log(tmp_path):
    def get(argv, timeout):
        if argv[1] == "get":
            (tmp_path / "logs").mkdir()
            (tmp_path / "logs" / "wish-20261001.log").write_text("x")
        return 0, "ok"

    files = winwish.collect_log(winwish.Guest(get), "h", tmp_path)
    assert files == ["wish-20261001.log"]
    with pytest.raises(winwish.WinwishError, match="no wish-"):
        winwish.collect_log(winwish.Guest(FakeRun()), "h", tmp_path / "empty")


# -- up and down --------------------------------------------------------------

def _args(tmp_path, monkeypatch, **extra):
    zipped = tmp_path / "wish-1.zip"
    zipped.write_bytes(b"PK")
    return winwish._parser().parse_args(
        ["up", "--sha", SHA, "--holder", "h", "--mute-proof", _mute(tmp_path, monkeypatch),
         "--df0", r"C:\Amiga\Disks\a.adf", "--zip", str(zipped), *extra])


def test_up_runs_the_steps_in_order(tmp_path, monkeypatch):
    run, lane = FakeRun(), FakeLane()
    winwish.up(winwish.Guest(run), lane, _args(tmp_path, monkeypatch))
    assert lane.log == ["claim", r"drives=C:\Amiga\Disks\a.adf", "start"]
    assert run.verbs() == ["ps", "put", "ps", "lane", "ps"]


def test_up_refuses_without_a_fresh_mute_proof(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    monkeypatch.setattr(winwish, "_mute_proof", lambda path: False)
    run, lane = FakeRun(), FakeLane()
    with pytest.raises(winwish.WinwishError, match="winuaemute"):
        winwish.up(winwish.Guest(run), lane, args)
    assert run.calls == [] and lane.log == []


START_FAILS = (lambda a: a[1] == "ps" and "Start-ScheduledTask" in a[2], 1,
               "fail no wish.exe window")


def test_up_stops_wish_then_winuae_then_releases_when_wish_does_not_start(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    run, lane = FakeRun([START_FAILS]), FakeLane()
    with pytest.raises(winwish.WinwishError):
        winwish.up(winwish.Guest(run), lane, args)
    stops = [c for c in run.calls if c[1] == "ps" and "Unregister-ScheduledTask" in c[2]]
    assert len(stops) == 1 and "'wish-run-h'" in stops[0][2]
    assert lane.log[-2:] == ["stop", "release"]


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_up_undoes_everything_on_an_interrupt_too(tmp_path, monkeypatch, exc):
    run, lane = FakeRun(), FakeLane(fail_on="start", exc=exc)
    with pytest.raises(exc):
        winwish.up(winwish.Guest(run), lane, _args(tmp_path, monkeypatch))
    assert lane.log[-1] == "release"


def test_up_does_not_stop_wish_when_it_never_tried_to_start_it(tmp_path, monkeypatch):
    run, lane = FakeRun(), FakeLane(fail_on="start")
    with pytest.raises(RouteError):
        winwish.up(winwish.Guest(run), lane, _args(tmp_path, monkeypatch))
    assert not [c for c in run.calls if c[1] == "ps" and "Unregister-ScheduledTask" in c[2]]


def test_up_releases_the_claim_when_winuae_does_not_start(tmp_path, monkeypatch):
    lane = FakeLane(fail_on="start")
    with pytest.raises(RouteError):
        winwish.up(winwish.Guest(FakeRun()), lane, _args(tmp_path, monkeypatch))
    assert lane.log[-1] == "release" and "stop" not in lane.log


def test_up_refuses_a_zip_fetched_for_another_commit(tmp_path, monkeypatch):
    args = _args(tmp_path, monkeypatch)
    (tmp_path / "commit.txt").write_text("f" * 40 + "\n")
    run, lane = FakeRun(), FakeLane()
    with pytest.raises(winwish.WinwishError, match="downloaded for"):
        winwish.up(winwish.Guest(run), lane, args)
    assert run.calls == [] and lane.log == []


def test_down_runs_every_step_even_when_the_first_fails():
    run = FakeRun([(lambda a: a[1] == "ps", 1, "fail wish.exe still running")])
    lane = FakeLane()
    with pytest.raises(winwish.WinwishError, match="wish: "):
        winwish.down(winwish.Guest(run), lane, "h")
    assert lane.log == ["stop", "release"]


# -- the command line ---------------------------------------------------------

def test_main_needs_a_holder_and_a_known_window():
    for argv in (["shot", "--out", "x"], ["shot", "--holder", "h", "--window", "tab", "--out", "x"],
                 ["up", "--sha", SHA, "--holder", "h"]):
        with pytest.raises(SystemExit):
            winwish.main(argv)


def test_main_prints_one_line_and_exits_1_on_a_guest_failure(capsys):
    run = FakeRun([(lambda a: a[1] == "lane", 1, "free")])
    assert winwish.main(["stop", "--holder", "h"], guest=winwish.Guest(run)) == 1
    assert capsys.readouterr().err.startswith("winwish: h does not hold")


def test_main_start_passes_no_flag_through(capsys):
    run = FakeRun()
    assert winwish.main(["start", "--holder", "h", "--no-flag"],
                        guest=winwish.Guest(run)) == 0
    script = run.calls[-1][2]
    body = base64.b64decode(script.split("-EncodedCommand ")[1].split("'")[0]).decode("utf-16-le")
    assert f"$env:{winwish.FLAG}" not in body
