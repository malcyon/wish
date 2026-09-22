"""`tools/amiga/winvmguest.py`, the agent guest's `winvm`, without a Windows guest.

Only the parts that decide something: the ssh and scp command lines and the
options no call may lose, the PowerShell it encodes, the screenshot read back
from the ssh output, the WinUAE lane read back from `winuae.ps1 status`, and the
desktop commands it refuses.  No ssh is run; the one test that goes through
`main` replaces `subprocess.run`.
"""

from __future__ import annotations

import base64
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.amiga import winvmguest as w  # noqa: E402

CFG = "/etc/ssh/ssh_config.d/wish-winvm.conf"


def _decode(encoded: str) -> str:
    return base64.b64decode(encoded).decode("utf-16-le")


# -- command lines ------------------------------------------------------------

def test_every_ssh_call_is_batch_mode_and_pinned():
    argv = w.ssh_argv(CFG, "win11", ["hostname"])
    assert argv[:3] == ["ssh", "-F", CFG]
    opts = " ".join(argv)
    assert "BatchMode=yes" in opts
    assert "StrictHostKeyChecking=yes" in opts
    assert "UpdateHostKeys=no" in opts
    assert argv[-2:] == ["win11", "hostname"]


def test_ssh_with_no_command_asks_for_a_tty_only_when_told():
    assert "-t" not in w.ssh_argv(CFG, "win11")
    assert w.ssh_argv(CFG, "win11", tty=True)[-2:] == ["-t", "win11"]


def test_put_turns_backslashes_into_forward_slashes():
    argv = w.put_argv(CFG, "win11", ["a.ps1", "b.uae"], r"C:\Amiga\configs")
    assert argv[:3] == ["scp", "-F", CFG]
    assert "StrictHostKeyChecking=yes" in " ".join(argv)
    assert argv[-3:] == ["a.ps1", "b.uae", "win11:C:/Amiga/configs"]


def test_put_with_nothing_to_copy_is_refused():
    with pytest.raises(w.WinvmError):
        w.put_argv(CFG, "win11", [], "C:/Amiga/")


def test_get_names_the_remote_side_first():
    argv = w.get_argv(CFG, "win11", r"C:\Amiga\send.log", ".", recursive=True)
    assert argv[-3:] == ["-r", "win11:C:/Amiga/send.log", "."]


def test_powershell_is_sent_encoded_so_no_shell_expands_it():
    script = 'Write-Output "$env:COMPUTERNAME" \'quoted\''
    cmd = w.powershell_command(script)
    assert cmd.startswith(w.POWERSHELL + " -EncodedCommand ")
    encoded = cmd.rsplit(" ", 1)[1]
    assert "$" not in encoded and '"' not in encoded and "'" not in encoded
    assert _decode(encoded) == script


# -- the screenshot -----------------------------------------------------------

def test_the_shot_runs_in_session_one_and_cleans_up_after_itself():
    script = w.shot_script("abc123", timeout=7)
    assert "-LogonType Interactive" in script
    assert "$task = 'winvm-shot-abc123'" in script
    assert "Unregister-ScheduledTask -TaskName $task" in script
    assert script.index("finally") < script.index("Unregister-ScheduledTask")
    assert "AddSeconds(7)" in script
    assert f"'{w.SHOT_BEGIN}'" in script and f"'{w.SHOT_END}'" in script


def test_the_capture_is_dpi_aware_and_written_by_rename():
    inner = w.shot_script("abc123").split("-EncodedCommand ", 1)[1].split("'", 1)[0]
    capture = _decode(inner)
    assert "SetProcessDPIAware" in capture
    assert "CopyFromScreen" in capture
    out = r"C:\Users\Public\winvm-shot-abc123.png"
    assert capture.rstrip().endswith(f"Move-Item -Force '{out}.tmp' '{out}'")


@pytest.mark.parametrize("token", ["", "a b", "x;y", "a" * 33, "../x"])
def test_a_token_that_could_break_the_script_is_refused(token):
    with pytest.raises(w.WinvmError):
        w.shot_script(token)


def test_the_png_is_read_back_from_between_the_markers():
    png = w.PNG_SIGNATURE + bytes(range(200))
    b64 = base64.encodebytes(png).decode()        # wrapped at 76, as PowerShell wraps
    out = f"noise\r\n{w.SHOT_BEGIN}\r\n{b64.replace(chr(10), chr(13) + chr(10))}{w.SHOT_END}\r\n"
    assert w.decode_shot(out) == png


def test_a_capture_that_failed_says_why():
    out = "fail no screenshot after 20s; lastResult=0x41303 -- nobody is logged on\r\n"
    with pytest.raises(w.WinvmError, match="nobody is logged on"):
        w.decode_shot(out)


def test_something_that_is_not_a_png_is_refused():
    b64 = base64.b64encode(b"GIF89a....").decode()
    with pytest.raises(w.WinvmError, match="not a PNG"):
        w.decode_shot(f"{w.SHOT_BEGIN}\n{b64}\n{w.SHOT_END}\n")


def test_shot_writes_the_file_it_was_handed(monkeypatch, tmp_path):
    png = w.PNG_SIGNATURE + b"pixels"
    seen = {}

    def _run(argv, **kwargs):
        seen["argv"] = argv
        body = base64.b64encode(png).decode()
        return types.SimpleNamespace(
            returncode=0, stderr="",
            stdout=f"{w.SHOT_BEGIN}\n{body}\n{w.SHOT_END}\n")

    monkeypatch.setattr(w.subprocess, "run", _run)
    out = tmp_path / "shots" / "s.png"
    assert w.main(["--config", CFG, "shot", str(out)]) == 0
    assert out.read_bytes() == png
    assert seen["argv"][:3] == ["ssh", "-F", CFG]
    assert list(out.parent.iterdir()) == [out]      # no temporary left behind


# -- status and the lane ------------------------------------------------------

STATUS_HELD = """\
host=WIN11-DEV\r
user=donald\r
boot=2026-09-22T08:00:00.0000000+00:00\r
pid=4242 session=1 responding=True start=09/22/2026 09:00:00\r
claim = por-run since 2026-09-22T09:00:00\r
run   = pid=4242 holder=por-run args=-log -f C:\\Amiga\\configs\\goldbox-a500.uae\r
System ROMs = C:\\Amiga\\Kickstarts\\\r
ROM database = 14 entries\r
"""

STATUS_FREE = """\
host=WIN11-DEV
user=donald
boot=2026-09-22T08:00:00
claim = none
run   = no receipt
System ROMs = C:\\Amiga\\Kickstarts\\
ROM database = 14 entries
"""


def test_a_held_lane_is_read_with_its_holder_and_emulator():
    st = w.parse_status(STATUS_HELD)
    assert (st.host, st.user) == ("WIN11-DEV", "donald")
    assert st.holder == "por-run"
    assert st.lane == "held by por-run since 2026-09-22T09:00:00"
    assert st.emulators == ["pid=4242 session=1 responding=True start=09/22/2026 09:00:00"]
    assert st.run.startswith("pid=4242 holder=por-run")
    assert w.lane_matches(st, "por-run")
    assert not w.lane_matches(st, "free")
    assert not w.lane_matches(st, "someone-else")


def test_a_free_lane_is_free():
    st = w.parse_status(STATUS_FREE)
    assert st.holder is None and st.lane == "free"
    assert st.emulators == []
    assert w.lane_matches(st, "free")


def test_no_driver_on_windows_is_never_a_free_lane():
    st = w.parse_status("host=WIN11-DEV\nuser=donald\nboot=x\ndriver=absent\n")
    assert not st.driver
    assert "not on the Windows guest" in st.lane
    assert not w.lane_matches(st, "free")


def test_a_driver_that_printed_no_claim_line_is_an_error_not_a_free_lane():
    with pytest.raises(w.WinvmError, match="no claim line"):
        w.parse_status("host=WIN11-DEV\nuser=donald\nboot=x\nsomething broke\n")


def test_the_status_script_asks_winuae_ps1_itself():
    script = w.status_script()
    assert f"-File '{w.WINUAE_PS1}' status" in script
    assert "driver=absent" in script


# -- what the desktop does and this does not ----------------------------------

@pytest.mark.parametrize("cmd", sorted(w.REFUSED))
def test_the_lifecycle_commands_are_refused_without_running_anything(
        monkeypatch, capsys, cmd):
    monkeypatch.setattr(w.subprocess, "run",
                        lambda *a, **k: pytest.fail("ran something"))
    assert w.main([cmd, "some-tag"]) == 2
    assert "not available in the agent guest" in capsys.readouterr().err


def test_a_lease_points_at_the_winuae_lane_instead():
    assert "winuae.ps1 claim" in w.REFUSED["acquire"]
    assert "winuae.ps1 release" in w.REFUSED["release"]
