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
import re
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

    def start(self, holder, *drives, timeout, options=()):
        self.log.append("drives=" + ",".join(drives))
        self.options = options
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


def test_stop_ends_this_holders_processes_before_it_reports_an_unreadable_one():
    script = winwish.stop_script("h")
    assert script.index("Stop-Process") < script.index("cannot tell")
    assert script.index("$mine.Count -gt 0") < script.index("-not $_.Path")


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


def _png() -> bytes:
    return (winvmguest.PNG_SIGNATURE + winvmguest.PNG_IHDR + bytes(17) + b"data"
            + winvmguest.PNG_IEND)


def test_shot_decodes_the_png_and_writes_it(tmp_path):
    png = _png()
    reply = "\n".join([winvmguest.SHOT_BEGIN, base64.b64encode(png).decode(), winvmguest.SHOT_END])
    run = FakeRun([(lambda a: a[1] == "ps", 0, reply)])
    out = tmp_path / "s" / "wish.png"
    assert winwish.shot(winwish.Guest(run), "h", "wish", out) == len(png)
    assert out.read_bytes() == png


def test_shot_keeps_a_complete_png_whatever_the_exit_code_was(tmp_path):
    png = _png()
    reply = "\n".join(["#< CLIXML", winvmguest.SHOT_BEGIN, base64.b64encode(png).decode(),
                       winvmguest.SHOT_END])
    run = FakeRun([(lambda a: a[1] == "ps", 1, reply)])
    out = tmp_path / "wish.png"
    assert winwish.shot(winwish.Guest(run), "h", "wish", out) == len(png)
    assert out.read_bytes() == png


def test_shot_fails_in_one_sentence_when_no_png_comes_back(tmp_path):
    for rc, reply in ((1, "ssh: connection refused"), (0, "ok"),
                      (1, f"{winvmguest.SHOT_BEGIN}\n{base64.b64encode(b'notapng').decode()}"
                          f"\n{winvmguest.SHOT_END}")):
        run = FakeRun([(lambda a: a[1] == "ps", rc, reply)])
        out = tmp_path / "none.png"
        with pytest.raises(winwish.WinwishError, match=rf"no screenshot came back \(winvm exit {rc}\)") as err:
            winwish.shot(winwish.Guest(run), "h", "wish", out)
        assert "\n" not in str(err.value)
        assert not out.exists()


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

def _args(tmp_path, monkeypatch, *extra):
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
    stops = [c for c in run.calls if c[1] == "ps" and "Stop-Process" in c[2]]
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
    assert not [c for c in run.calls if c[1] == "ps" and "Stop-Process" in c[2]]


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


# `os.kill(pid, SIGTERM)` on Windows is `TerminateProcess`: no handler runs, so
# signalling itself kills the pytest worker and the Windows job never reports.
@pytest.mark.skipif(sys.platform == "win32",
                    reason="SIGTERM has no handler on Windows")
def test_a_second_sigterm_during_the_undo_does_not_skip_the_release(tmp_path, monkeypatch):
    import os
    import signal

    class Lane(FakeLane):
        def stop(self, holder, timeout):
            os.kill(os.getpid(), signal.SIGTERM)     # a second one, mid-undo
            return super().stop(holder, timeout)

    lane = Lane()
    with pytest.raises(winwish.WinwishError):
        winwish.up(winwish.Guest(FakeRun([START_FAILS])), lane, _args(tmp_path, monkeypatch))
    assert lane.log[-1] == "release"


def test_an_interrupt_inside_one_undo_step_still_releases(tmp_path, monkeypatch):
    class Lane(FakeLane):
        def stop(self, holder, timeout):
            raise KeyboardInterrupt

    lane = Lane()
    args = _args(tmp_path, monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        winwish.up(winwish.Guest(FakeRun([START_FAILS])), lane, args)
    assert lane.log[-1] == "release"


def test_a_zip_with_no_commit_note_says_so(tmp_path, capsys):
    zipped = tmp_path / "wish-1.zip"
    zipped.write_bytes(b"PK")
    winwish.check_zip_commit(zipped, SHA)
    assert "no commit.txt" in capsys.readouterr().err


def test_up_passes_a_third_and_fourth_drive_with_the_settings_they_need(tmp_path, monkeypatch):
    lane = FakeLane()
    args = _args(tmp_path, monkeypatch, "--df1", "b.adf", "--df2", "c.adf")
    winwish.up(winwish.Guest(FakeRun()), lane, args)
    assert "drives=" + r"C:\Amiga\Disks\a.adf,b.adf,c.adf" in lane.log
    assert lane.options == ("nr_floppies=3", "floppy2type=0")
    lane = FakeLane()
    args = _args(tmp_path, monkeypatch, "--df1", "b.adf", "--df2", "c.adf", "--df3", "d.adf")
    winwish.up(winwish.Guest(FakeRun()), lane, args)
    assert lane.options == ("nr_floppies=4", "floppy2type=0", "floppy3type=0")


def test_two_drives_or_fewer_add_no_settings(tmp_path, monkeypatch):
    lane = FakeLane()
    winwish.up(winwish.Guest(FakeRun()), lane, _args(tmp_path, monkeypatch, "--df1", "b.adf"))
    assert lane.options == ()


def test_a_drive_after_a_gap_is_refused_before_anything_starts(tmp_path, monkeypatch):
    run, lane = FakeRun(), FakeLane()
    args = _args(tmp_path, monkeypatch, "--df2", "c.adf")
    with pytest.raises(winwish.WinwishError, match="without a gap"):
        winwish.up(winwish.Guest(run), lane, args)
    assert lane.log == [] and run.calls == []


def test_an_empty_df0_is_refused_in_one_sentence(tmp_path, monkeypatch):
    run, lane = FakeRun(), FakeLane()
    args = _args(tmp_path, monkeypatch)
    args.df0 = ""
    with pytest.raises(winwish.WinwishError, match="--df0 needs"):
        winwish.up(winwish.Guest(run), lane, args)
    assert lane.log == [] and run.calls == []


def test_the_drive_settings_become_dash_s_arguments():
    from tools.amiga.winuaesession import WinGuest  # noqa: PLC0415
    sent = []
    guest = WinGuest()
    guest._lane = lambda holder, command, timeout: sent.append(command) or "ok"
    guest.start("h", "a.adf", "b.adf", "c.adf", timeout=1,
                options=winwish.floppy_options(3))
    assert "-s floppy2=c.adf" in sent[0]
    assert "-s nr_floppies=3 -s floppy2type=0" in sent[0]


# -- PowerShell reads `$name:` in a double-quoted string as a drive-qualified variable --

def _double_quoted(script: str) -> list[str]:
    """The literal text of each double-quoted string in `script`.

    Single-quoted strings and here-strings are skipped. A `$(...)` inside a double-quoted
    string is cut out of the outer string's text, and the double-quoted strings
    inside it are returned as strings of their own. A backtick escapes the next character.
    """
    found: list[str] = []

    def double(i: int) -> int:
        """Read the string whose opening quote is at `i`; return the index after it."""
        text, i = [], i + 1
        while script[i] != '"':
            if script[i] == "`":
                text.append("  ")
                i += 2
            elif script.startswith("$(", i):
                text.append(" ")
                i = code(i + 2, ")")
            else:
                text.append(script[i])
                i += 1
        found.append("".join(text))
        return i + 1

    def code(i: int, closer: str) -> int:
        """Skip PowerShell code up to the `closer` that ends it, reading strings in it."""
        depth = 0
        while True:
            c = script[i]
            if script.startswith("@'", i):
                i = script.index("\n'@", i) + 3
            elif c == "'":
                i += 1
                while not (script[i] == "'" and script[i + 1:i + 2] != "'"):
                    i += 2 if script[i] == "'" else 1
                i += 1
            elif c == '"':
                i = double(i)
            elif c == "(" and closer == ")":
                depth += 1
                i += 1
            elif c == closer and depth:
                depth -= 1
                i += 1
            elif c == closer:
                return i + 1
            else:
                i += 1

    i = 0
    while i < len(script):
        if script.startswith("@'", i) or script[i] in "'\"":
            i = code_one(script, i, double)
        else:
            i += 1
    return found


def code_one(script: str, i: int, double) -> int:
    """Read one quoted item that starts at `i` and return the index after it."""
    if script.startswith("@'", i):
        return script.index("\n'@", i) + 3
    if script[i] == '"':
        return double(i)
    i += 1
    while not (script[i] == "'" and script[i + 1:i + 2] != "'"):
        i += 2 if script[i] == "'" else 1
    return i + 1


#: Scope names PowerShell resolves as a variable scope or provider, so `$env:Name` is meant.
SCOPES = ("env", "script", "global", "local", "private", "using")
REFERENCE = re.compile(r"\$(\w+):")


def bad_references(string: str) -> list[str]:
    """Every `$name:` in a string's literal text where `name` is not a scope.

    PowerShell reads `$name:rest` as the variable `rest` on drive `name`, so
    `"$run:retry"` fails to find a drive. A `$` after a backtick is a literal dollar
    sign and is blanked out before the search.
    """
    return [m.group(0) for m in REFERENCE.finditer(string.replace("`$", "  "))
            if m.group(1).lower() not in SCOPES]


def _every_script():
    env = winwish.environment(True, "h")
    return {
        "stage": winwish.stage_script("h", r"C:\z.zip", "a" * 64),
        "mkdir": winwish.mkdir_script(r"C:\x"),
        "start": winwish.start_script("h", env),
        "start-control": winwish.start_script("h", winwish.environment(False, "h")),
        "task": winwish._task_body(env, winwish.build_root("h"), True),
        "ui-controls": winwish.ui_inner(r"C:\\b", "controls", (), "RadioButton", r"C:\\o.txt"),
        "ui-click": winwish.ui_inner(r"C:\\b", "click", ("File", "Preferences..."), None, r"C:\\o.txt"),
        "ui-ssh": winwish.ui_script("abc", 30),
        "probe": winwish.window_probe(r"C:\\o.txt", r"C:\\b"),
        "stop": winwish.stop_script("h"),
        "capture": winwish.window_capture(r"C:\o.png", "h"),
    }


@pytest.mark.parametrize("name", list(_every_script()))
def test_no_generated_script_has_a_dollar_name_colon_in_a_double_quoted_string(name):
    strings = _double_quoted(_every_script()[name])
    assert strings or name in ("mkdir", "task", "probe", "ui-controls")
    assert [bad for s in strings for bad in bad_references(s)] == []


def test_the_scanner_catches_a_drive_reference_however_it_continues():
    for text in ('"from $run: its"', '"$run:retry"', '"$run:\\x"', '"a $($x.Id) $run:"'):
        found = [bad for s in _double_quoted(text) for bad in bad_references(s)]
        assert found == ["$run:"], text


def test_the_scanner_passes_what_powershell_accepts():
    for text in ('"$env:USERNAME"', '"${run}:retry"', '"`$run: x"', "'$run: x'",
                 '"$($x[\'a\'].Id): ok"', '"$script:n $using:v"'):
        assert [bad for s in _double_quoted(text) for bad in bad_references(s)] == [], text


def test_the_scanner_reads_a_string_nested_in_a_subexpression():
    found = _double_quoted('"a $(Join-Path "$run:x" b) c"')
    assert len(found) == 2 and bad_references(found[0]) == ["$run:"]


# -- the window check ----------------------------------------------------------

def _start() -> str:
    return winwish.start_script("h", winwish.environment(True, "h"))


def test_the_window_is_looked_for_by_a_task_in_session_one_not_over_ssh():
    script = _start()
    assert "MainWindowHandle" not in script
    assert "Register-ScheduledTask -TaskName $probe" in script
    assert "Start-ScheduledTask -TaskName $probe" in script
    assert "'wish-probe-h'" in script


def test_the_probe_lists_the_class_and_title_of_every_window_of_a_wish_process():
    probe = winwish.window_probe(r"C:\o.txt", r"C:\b")
    for call in ("EnumWindows", "GetWindowThreadProcessId", "IsWindowVisible",
                 "GetClassName", "GetWindowText"):
        assert call in probe
    assert "Get-Process -Name wish" in probe
    assert r"Move-Item -Force 'C:\o.txt.tmp' 'C:\o.txt'" in probe


def test_the_check_wants_a_visible_window_titled_as_the_main_window_is():
    script = _start()
    assert "$f[2] -eq '1' -and $f[4] -like 'Wish*'" in script
    # `WishWindow.setWindowTitle` and `_retitle`: "Wish", then " [logging]" with the log on.
    ui = (pathlib.Path(winwish.__file__).parents[2] / "wish" / "ui_window.py").read_text()
    assert 'WishWindow.setWindowTitle(_translate("WishWindow", "Wish"))' in ui


def test_a_failed_check_lists_the_processes_and_the_windows_it_found():
    script = _start()
    assert 'wish pid=$($_.Id) session=$($_.SessionId) path=$($_.Path)' in script
    assert '"  window $_"' in script
    assert "no top-level window belongs to a wish process" in script
    fail = script[script.index("fail no wish.exe window titled Wish"):]
    assert fail.index("$procs") < fail.index("$seen") < fail.index("exit 1")


def test_stopping_removes_the_probe_task_too():
    assert "Unregister-ScheduledTask -TaskName 'wish-probe-h'" in winwish.stop_script("h")


# -- review of the window check -------------------------------------------------

def test_the_probe_lists_only_windows_of_a_wish_under_this_holders_build():
    probe = winwish.window_probe(r"C:\o.txt", r"C:\Amiga\wish\run-h\build")
    assert "$script:build = 'C:\\Amiga\\wish\\run-h\\build'" in probe
    assert 'Where-Object { $_.Path -like "$script:build\\*" }' in probe
    start = _start()
    assert r"C:\Amiga\wish\run-h\build" in start


def test_the_start_script_always_removes_the_probe_task():
    script = _start()
    assert "} finally { Close-Probe }" in script
    assert "Get-Process -Id ([int]$f[1]) -ErrorAction SilentlyContinue" in script
    assert "if (-not $owner) { continue }" in script


def test_a_start_that_fails_removes_the_probe_task_over_ssh_too():
    run = FakeRun([START_FAILS])
    with pytest.raises(winwish.WinwishError):
        winwish.start_wish(winwish.Guest(run), "h")
    last = run.calls[-1][2]
    assert "Unregister-ScheduledTask -TaskName 'wish-probe-h'" in last
    assert "Start-ScheduledTask" not in last


def test_the_probe_is_started_only_when_the_task_is_ready():
    script = _start()
    ready = script.index("State -ne 'Ready'")
    assert ready < script.index("Start-ScheduledTask -TaskName $probe")
    assert "the window probe was still running" in script


def test_the_probe_loop_never_runs_past_the_wait():
    script = _start()
    assert "$left = ($deadline - (Get-Date)).TotalSeconds" in script
    assert "if ($left -lt 1) { break }" in script
    assert "Get-WishWindows ([Math]::Min(10, $left))" in script


def test_every_title_wish_shows_starts_with_wish():
    root = pathlib.Path(winwish.__file__).parents[2] / "wish"
    window = (root / "window.py").read_text(encoding="utf-8")
    assert 'getattr(self, "_editor_title", "Wish")' in window
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\._retitle\([^)\s]", text), path
        if path.name != "window.py":
            assert "_editor_title" not in text, path


# -- the game folder Wish is started with --------------------------------------

def test_the_seeded_settings_name_the_guest_folder_and_wish_resolves_it(tmp_path, monkeypatch):
    from automap import config, paths  # noqa: PLC0415
    from goldbox import c64_port  # noqa: PLC0415
    pool = c64_port.GAMES[0]
    folder = winwish.disks_dir("h")
    seeded = json.loads(winwish.settings_json(pool.key, folder))
    assert seeded == {"diagnostics": True, "game_folders": {pool.key: folder}}
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    (tmp_path / config.FILE).write_text(winwish.settings_json(pool.key, folder), encoding="utf-8")
    loaded = config.Settings.load()
    assert loaded.diagnostics is True
    where, source = paths.resolve_disks(game=pool, settings=loaded)
    assert str(where) == folder and source == paths.GAME_PREFERENCE


def test_without_a_game_the_settings_are_as_they_were():
    assert json.loads(winwish.settings_json()) == {"diagnostics": True}


def test_start_copies_the_adfs_per_drive_and_writes_the_folder_when_asked():
    disks = (r"C:\Amiga\Disks\disk.adf", r"C:\Amiga\Other\disk.adf")
    script = winwish.start_script("h", winwish.environment(True, "h"), disks=disks,
                                  game="pool-of-radiance")
    folder = winwish.disks_dir("h")
    assert f"Remove-Item -Path '{folder}\\*' -Recurse -Force" in script
    assert (f"Copy-Item -LiteralPath 'C:\\Amiga\\Disks\\disk.adf' "
            f"-Destination '{folder}\\df0-disk.adf' -Force") in script
    assert (f"Copy-Item -LiteralPath 'C:\\Amiga\\Other\\disk.adf' "
            f"-Destination '{folder}\\df1-disk.adf' -Force") in script
    assert "pool-of-radiance" in script and "game_folders" in script
    assert "if (-not (Test-Path -LiteralPath $settings))" not in script


def test_only_the_game_disks_are_copied_not_the_save_disk(tmp_path, monkeypatch):
    run, lane = FakeRun(), FakeLane()
    args = _args(tmp_path, monkeypatch, "--df1", "b.adf", "--df2", "save.adf",
                 "--game", "pool-of-radiance")
    winwish.up(winwish.Guest(run), lane, args)
    start = next(c[2] for c in run.calls if c[1] == "ps" and "Register-ScheduledTask -TaskName $task" in c[2])
    assert "b.adf" in start and "save.adf" not in start
    assert lane.log[1].count(",") == 2  # the save disk is still mounted in DF2


def test_a_plain_start_keeps_the_settings_an_earlier_up_wrote():
    script = winwish.start_script("h", winwish.environment(True, "h"), reseed=False)
    assert "if (-not (Test-Path -LiteralPath $settings)) { [IO.File]::WriteAllText($settings" in script
    assert "Copy-Item" not in script


def test_up_gives_the_game_and_the_mounted_adfs_to_the_start(tmp_path, monkeypatch):
    run, lane = FakeRun(), FakeLane()
    args = _args(tmp_path, monkeypatch, "--df1", "b.adf", "--game", "pool-of-radiance")
    winwish.up(winwish.Guest(run), lane, args)
    starts = [c[2] for c in run.calls if c[1] == "ps" and "Register-ScheduledTask -TaskName $task" in c[2]]
    assert len(starts) == 1
    assert "pool-of-radiance" in starts[0] and "b.adf" in starts[0]


def test_a_game_key_that_is_not_one_is_refused_before_anything_runs(tmp_path, monkeypatch):
    run, lane = FakeRun(), FakeLane()
    args = _args(tmp_path, monkeypatch, "--game", "Pool; rm")
    with pytest.raises(winwish.WinwishError, match="not a game key"):
        winwish.up(winwish.Guest(run), lane, args)
    assert run.calls == [] and lane.log == []


# -- clicking Wish -----------------------------------------------------------------

def _ui_reply(*lines):
    return "\n".join(["#< CLIXML", winwish.UI_BEGIN, *lines, winwish.UI_END])


def test_controls_returns_the_lines_after_ok():
    run = FakeRun([(lambda a: a[1] == "ps" and "wish-ui-" in a[2], 1,
                    _ui_reply("ok", "RadioButton|WinUAE (Amiga)||enabled=True|selected=False"))])
    lines = winwish.ui(winwish.Guest(run), "h", "controls", (), "RadioButton")
    assert lines == ["RadioButton|WinUAE (Amiga)||enabled=True|selected=False"]
    assert run.calls[0][:3] == ["winvm", "lane", "--expect"]


def test_a_failure_line_from_the_window_is_the_error():
    run = FakeRun([(lambda a: a[1] == "ps", 0, _ui_reply("fail Heal party is disabled"))])
    with pytest.raises(winwish.WinwishError, match="Heal party is disabled"):
        winwish.ui(winwish.Guest(run), "h", "click", ("Heal party",))


def test_no_answer_at_all_is_one_sentence():
    run = FakeRun([(lambda a: a[1] == "ps", 1, "ssh: nope")])
    with pytest.raises(winwish.WinwishError, match="answered with nothing"):
        winwish.ui(winwish.Guest(run), "h", "controls")


def test_the_click_script_checks_enabled_before_invoking_and_walks_every_window():
    inner = winwish.ui_inner(r"C:\b", "click", ("File", "Preferences..."), None, r"C:\o.txt")
    assert "if (-not $hit[0].Current.IsEnabled) { throw" in inner
    assert inner.index("IsEnabled) { throw") < inner.index("Use-Control $hit[0]")
    assert "$names = @('File', 'Preferences...')" in inner
    assert "RootElement.FindAll([System.Windows.Automation.TreeScope]::Children" in inner
    assert "InvokePattern" in inner and "SelectionItemPattern" in inner


def test_the_ui_task_is_removed_whatever_happens():
    script = winwish.ui_script("abc", 30)
    assert script.index("} finally {") < script.index("Unregister-ScheduledTask -TaskName $task")
    assert script.rstrip().endswith("exit 0")


def test_the_cli_has_controls_and_click(monkeypatch, capsys):
    run = FakeRun([(lambda a: a[1] == "ps", 0, _ui_reply("ok", "File -> invoked"))])
    assert winwish.main(["click", "--holder", "h", "File"], winwish.Guest(run)) == 0
    assert "File -> invoked" in capsys.readouterr().out


# -- what Windows will run ---------------------------------------------------------

LIMIT = 32767  # CreateProcess's command line limit; past it ssh says "exec request failed"


def test_no_script_is_too_long_for_a_windows_command_line():
    disks = (r"C:\Amiga\Disks\wish37-j37wfix-with-a-long-name-disk1.adf",) * 4
    worst = "j37wfix-with-a-long-holder"[:32]
    start = winwish.start_script(worst, winwish.environment(True, worst), disks=disks,
                                 game="secret-of-the-silver-blades")
    ui = winwish.ui_script("abcdef123456", 99)
    for script in (start, ui):
        assert len(winvmguest.powershell_command(script)) < LIMIT - 4000


def test_the_probe_and_ui_scripts_travel_as_files_not_as_nested_commands():
    start = _start()
    assert '-File "C:\\Amiga\\wish\\run-h\\probe.ps1"' in start
    assert start.count("-EncodedCommand") == 1  # the task body only
    ui = winwish.ui_script("abc", 30)
    assert '-File "C:\\Users\\Public\\wish-ui-abc.ps1"' in ui
    assert "-EncodedCommand" not in ui


def test_ui_puts_its_script_on_the_guest_before_running_it():
    run = FakeRun([(lambda a: a[1] == "ps", 0, _ui_reply("ok"))])
    winwish.ui(winwish.Guest(run), "h", "controls")
    verbs = [c[1] for c in run.calls]
    assert verbs == ["lane", "put", "ps"]
    put = run.calls[1]
    assert put[3].startswith("C:/Users/Public/wish-ui-") and put[3].endswith(".ps1")


def test_more_names_than_the_limit_are_refused_before_anything_runs():
    run = FakeRun()
    with pytest.raises(winwish.WinwishError, match="at most"):
        winwish.ui(winwish.Guest(run), "h", "click", tuple("abcdefghi"))
    assert run.calls == []


def test_the_wait_grows_with_the_number_of_names():
    assert winwish.ui_timeout(1) < winwish.ui_timeout(2) < winwish.ui_timeout(winwish.UI_MAX_NAMES)
    assert winwish.ui_timeout(winwish.UI_MAX_NAMES) < 120  # the task is stopped after two minutes


def test_write_file_round_trips_through_base64_with_a_bom():
    statement = winwish.write_file(r"C:\x.ps1", "caf\u00e9 $x")
    data = base64.b64decode(statement.split("FromBase64String('")[1].split("'")[0])
    assert data == b"\xef\xbb\xbf" + "caf\u00e9 $x".encode("utf-8")


def test_a_menu_opens_by_expanding_and_a_modal_item_is_invoked_off_thread():
    inner = winwish.ui_inner(r"C:\b", "click", ("File",), None, r"C:\o.txt")
    assert inner.index("ExpandCollapsePattern]::Pattern, [ref]$o)) { $o.Expand()") \
        < inner.index("InvokePattern]::Pattern, [ref]$o)) { return (Start-Async $o) }")
    assert "[PowerShell]::Create()" in inner and "BeginInvoke()" in inner
    assert "WindowPattern]::Pattern, [ref]$o)) { $o.Close(); return 'closed' }" in inner


def test_an_invoke_error_is_reported_and_a_running_one_is_named():
    inner = winwish.ui_inner(r"C:\b", "click", ("File",), None, r"C:\o.txt")
    assert "if (-not $handle.IsCompleted) { return 'invoked (still running: modal?)' }" in inner
    assert "$ps.EndInvoke($handle)" in inner and "$ps.HadErrors" in inner
    assert "} finally { $ps.Dispose() }" in inner


def test_the_task_is_stopped_before_it_is_removed_and_the_inner_script_exits():
    script = winwish.ui_script("abc", 30)
    assert script.index("Stop-ScheduledTask -TaskName $task") \
        < script.index("Unregister-ScheduledTask -TaskName $task")
    inner = winwish.ui_inner(r"C:\b", "click", ("File",), None, r"C:\o.txt")
    assert inner.rstrip().endswith("[Environment]::Exit(0)")
    assert inner.index("Move-Item") < inner.index("[Environment]::Exit(0)")


def test_names_match_exactly_for_the_whole_wait_and_a_prefix_only_when_asked():
    plain = winwish.ui_inner(r"C:\b", "click", ("File",), None, r"C:\o.txt")
    asked = winwish.ui_inner(r"C:\b", "click", ("File",), None, r"C:\o.txt", prefix=True)
    assert "$prefix = $false" in plain and "$prefix = $true" in asked
    assert "if ($hit.Count -eq 0 -and $expired -and $prefix)" in plain
    assert "[void]$lines.Add($hit[0].Current.Name + ' -> '" in plain
    assert "if ((Get-Date) -gt $until) { if ($prefix) { $expired = $true } else { break } }" in plain


def test_every_wish_of_the_holder_is_searched_not_the_first():
    inner = winwish.ui_inner(r"C:\b", "controls", (), None, r"C:\o.txt")
    assert "foreach ($proc in $procs)" in inner
    assert "$proc = Get-Process" not in inner


def test_a_window_with_no_children_is_read_through_msaa():
    inner = winwish.ui_inner(r"C:\b", "controls", (), "RadioButton", r"C:\o.txt")
    assert "Get-Msaa $e.Current.NativeWindowHandle" in inner and "AccessibleObjectFromWindow" in inner
    assert "$parent.accChildCount" in inner
    assert "MSAA|" in inner


def test_the_cli_takes_a_prefix_flag():
    args = winwish._parser().parse_args(["click", "--holder", "h", "--prefix", "File"])
    assert args.prefix is True


def test_the_answer_is_ascii_whatever_a_control_is_called():
    inner = winwish.ui_inner(r"C:\b", "controls", (), None, r"C:\o.txt")
    assert "[^\\x20-\\x7e]" in inner and "x4" in inner


def test_an_undecodable_byte_in_the_guest_reply_does_not_raise(monkeypatch):
    import subprocess  # noqa: PLC0415

    def fake(argv, **kwargs):
        assert kwargs["errors"] == "replace"
        return subprocess.CompletedProcess(argv, 0, "ok \ufffd", "")
    monkeypatch.setattr(subprocess, "run", fake)
    assert winwish._run(["winvm", "ps", "x"], 5)[1] == "ok \ufffd"


# -- the MSAA rows, parsed here ------------------------------------------------------

@pytest.mark.parametrize("role, kind", [
    (9, "Window"), (11, "Menu"), (12, "MenuItem"), (20, "Group"), (22, "ToolBar"), (28, "Row"),
    (33, "List"), (34, "ListItem"), (37, "TabItem"), (41, "Text"), (42, "Edit"), (43, "Button"),
    (44, "CheckBox"), (45, "RadioButton"), (46, "ComboBox"), (47, "ComboBox"), (60, "Tab")])
def test_the_msaa_role_numbers_are_the_role_system_constants(role, kind):
    assert winwish.msaa_line(f"{role}|n||0")[0] == kind


def test_an_msaa_row_becomes_a_controls_line():
    assert winwish.msaa_line("45|WinUAE (Amiga)||16") == (
        "RadioButton", "RadioButton|WinUAE (Amiga)||enabled=True|checked=True (MSAA)")
    assert winwish.msaa_line("43|Close||1")[1].endswith("enabled=False|checked=False (MSAA)")
    assert winwish.msaa_line("999|x||0")[0] == "Role999"
    assert winwish.msaa_line("-1|||0") == ("", "...truncated")


def test_a_bar_in_a_name_survives_the_escape():
    assert winwish.msaa_line("41|a\\u007cb|c\\u007cd|0")[1] == "Text|a|b|c|d|enabled=True|checked=False (MSAA)"


def test_the_type_filter_applies_to_msaa_rows_here_and_keeps_the_truncation_marker():
    reply = _ui_reply("ok", "Window|Preferences||enabled=True|", "MSAA|45|A||16", "MSAA|43|B||0",
                      "MSAA|-1|||0")
    assert winwish.ui_lines(reply, "RadioButton") == [
        "Window|Preferences||enabled=True|", "RadioButton|A||enabled=True|checked=True (MSAA)",
        "...truncated"]
    assert len(winwish.ui_lines(reply)) == 4


def test_the_walk_caps_its_count_and_says_when_it_stopped_early():
    inner = winwish.ui_inner(r"C:\b", "controls", (), None, r"C:\o.txt")
    assert "$got = [Math]::Min($got, $n)" in inner
    assert "$script:cut = $true" in inner and "[void]$rows.Add('-1|||0')" in inner
    assert inner.count("$script:cut = $true") >= 4  # depth or rows, count throws, too many, children throws
    assert "-replace '\\|', '\\u007c'" in inner
    assert "$roles" not in inner


def test_controls_gets_a_longer_base_timeout_than_a_click():
    assert winwish.ui_timeout(0, "controls") > winwish.ui_timeout(1, "click")
    assert winwish.ui_timeout(0, "controls") < 120


def test_the_put_script_is_removed_when_the_call_fails():
    run = FakeRun([(lambda a: a[1] == "ps" and "wish-ui-" in a[2] and "Register" in a[2], 1, "boom")])
    with pytest.raises(winwish.WinwishError):
        winwish.ui(winwish.Guest(run), "h", "controls")
    last = run.calls[-1]
    assert last[1] == "ps" and "Remove-Item -LiteralPath 'C:\\Users\\Public\\wish-ui-" in last[2]
    ok = FakeRun([(lambda a: a[1] == "ps", 0, _ui_reply("ok"))])
    winwish.ui(winwish.Guest(ok), "h", "controls")
    assert [c[1] for c in ok.calls] == ["lane", "put", "ps"]


def test_the_seeded_disk_folder_is_cleared_recursively():
    script = winwish.start_script("h", winwish.environment(True, "h"), disks=("a.adf",),
                                  game="pool-of-radiance")
    assert "-Recurse -Force -ErrorAction SilentlyContinue" in script.split("Copy-Item")[0].split("Remove-Item -Path")[1]
