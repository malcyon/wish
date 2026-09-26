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
import re
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
    assert argv[-4:] == ["-r", "--", "win11:C:/Amiga/send.log", "."]


def test_scp_argv_puts_a_separator_before_the_paths():
    argv = w.scp_argv(CFG, ["a"], "win11:C:/b")
    assert "--" in argv
    assert argv[argv.index("--") + 1:] == ["a", "win11:C:/b"]


def test_scp_argv_rejects_a_path_that_looks_like_an_option():
    with pytest.raises(w.ScpArgumentError):
        w.scp_argv(CFG, ["-oProxyCommand=x"], "win11:C:/b")
    with pytest.raises(w.ScpArgumentError):
        w.scp_argv(CFG, ["a"], "-oProxyCommand=x")


def test_winvm_scp_exits_2_on_a_dashed_argument_without_running_anything(
        monkeypatch, capsys):
    monkeypatch.setattr(w.subprocess, "run",
                        lambda *a, **k: pytest.fail("ran something"))
    assert w.main(["scp", "-oProxyCommand=x", "a", "win11:C:/b"]) == 2
    assert "starts with '-'" in capsys.readouterr().err


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


# -- the lane script's `drives` and `insert` verbs ---------------------------------
#
# There is no PowerShell here, so these pin the structure of the script text: what
# is checked, in what order, and the exact messages that go down the pipe. What the
# script does on the guest is measured by the drive-check probe.

WINUAE_PS1 = (pathlib.Path(__file__).resolve().parents[2] / "tools" / "amiga"
              / "winuae.ps1").read_text()
FLOPPY = WINUAE_PS1[WINUAE_PS1.index("function Invoke-Floppy"):
                    WINUAE_PS1.index("switch ($Cmd) {")]


def _at(needle: str, start: int = 0) -> int:
    at = FLOPPY.find(needle, start)
    assert at >= 0, needle
    return at


def test_the_lane_script_accepts_the_two_new_verbs():
    valid = re.search(r"ValidateSet\(([^)]*)\)", WINUAE_PS1).group(1)
    assert "'drives'" in valid and "'insert'" in valid
    assert "'drives' {" in WINUAE_PS1 and "'insert' {" in WINUAE_PS1


def test_ownership_is_checked_before_the_pipe_is_opened_and_twice_more_after():
    opened = _at("New-Object IO.Pipes.NamedPipeClientStream")
    assert FLOPPY.count("Get-LaneEmulator") == 2
    assert _at("Get-LaneEmulator") < opened < _at("Get-LaneEmulator", opened)
    setter = _at('Send-Pipe $pipe "CFG floppy$drive $path"')
    assert opened < _at("Claim-Denial", opened) < setter
    assert _at("Claim-Denial") < opened


def test_the_lane_emulator_check_reuses_the_claim_and_receipt_functions():
    body = WINUAE_PS1[WINUAE_PS1.index("function Get-LaneEmulator"):
                      WINUAE_PS1.index("function Send-Pipe")]
    assert body.index("Claim-Denial") < body.index("Resolve-MyEmulator") < body.index("ExecutablePath")
    assert "$path -ne $Exe" in body
    assert "claim token is not the one" in body


def test_the_pipe_is_bound_to_the_lanes_own_process():
    assert "GetNamedPipeServerProcessId" in FLOPPY
    assert _at("GetNamedPipeServerProcessId") < _at("$server -ne $lane.proc.Id")
    assert _at("$server -ne $lane.proc.Id") < _at('Send-Pipe $pipe "CFG floppy$drive $path"')


def test_the_file_and_its_hash_are_checked_before_the_pipe_is_opened():
    opened = _at("New-Object IO.Pipes.NamedPipeClientStream")
    assert _at("Test-Path -LiteralPath $path -PathType Leaf") < opened
    assert _at("Get-FileHash -LiteralPath $path") < opened
    assert "does not exist" in FLOPPY
    assert re.search(r"if \(\$got -ne \$want\.ToUpper\(\)\) \{ \"fail \$path hashes[^}]*exit 1 \}", FLOPPY)


def test_the_drive_path_and_holder_are_validated_in_the_guest_too():
    assert "'^[01]$'" in FLOPPY
    assert "$path.Length -gt 200" in FLOPPY and "$path.Contains('..')" in FLOPPY
    assert "StartsWith(\"$Holder-\", [StringComparison]::Ordinal)" in FLOPPY
    assert "is not staged for $Holder" in FLOPPY
    assert "'^[0-9A-Fa-f]{64}$'" in FLOPPY


def test_the_guest_sends_exactly_one_setter_of_exactly_two_tokens():
    assert FLOPPY.count("CFG floppy$drive $path") == 1
    assert re.findall(r'Send-Pipe \$pipe "([^"]*)"', FLOPPY) == ["CFG floppy$drive $path"]
    reads = WINUAE_PS1[WINUAE_PS1.index("function Read-Drives"):WINUAE_PS1.index("function Invoke-Floppy")]
    assert re.findall(r"@\('(\w+)', '([^']*)'\)", reads) == [
        ("q0", "CFG floppy0"), ("q1", "CFG floppy1"), ("dbg", "DBG c")]
    assert "ipc_" not in WINUAE_PS1.lower()


def test_the_setter_is_reachable_only_when_writing_and_only_once_the_pre_read_allows_it():
    setter = _at('Send-Pipe $pipe "CFG floppy$drive $path"')
    guard = FLOPPY.rindex("if (-not $verdict -and $write)", 0, setter)
    assert guard > _at("$before = Read-Drives")
    assert FLOPPY.count("Send-Pipe $pipe") == 1
    assert "is already in DF$o" in FLOPPY and "ok already drive=$drive" in FLOPPY


def test_a_message_goes_down_with_its_terminating_nul_and_one_poll_is_bounded():
    send = WINUAE_PS1[WINUAE_PS1.index("function Send-Pipe"):WINUAE_PS1.index("function Read-Drives")]
    assert "New-Object byte[] ($b.Length + 1)" in send and "ASCII.GetBytes" in send
    assert "$PollBoundMs = 10000" in WINUAE_PS1 and "$PollEveryMs = 250" in WINUAE_PS1


def test_the_guest_regexes_accept_what_the_python_ones_accept():
    from automap import amiga

    staged = re.search(r"\$DiskPattern = '([^']*)'", WINUAE_PS1).group(1).replace(r"\z", r"\Z")
    cases = [
        r"C:\Amiga\Disks\wish679-h-probeA.adf", r"C:\Amiga\Disks\wish679-h.x-a.b.adf",
        r"C:\Amiga\Disks\wish679-h-.adf", r"C:\Amiga\Disks\wish679-h-a..b.adf",
        r"C:\Amiga\Disks\wish-x.adf", r"C:\Amiga\Disks\wish679-x.zip",
        "C:\\Amiga\\Disks\\wish679-x.adf\n", r"C:\Amiga\Disks\..\wish1-x.adf",
        r"D:\Amiga\Disks\wish679-x.adf", r"\\server\Disks\wish679-x.adf",
        r"C:\Amiga\Disks\wish679-a b.adf", r"C:\Amiga\Disks\wish679-a=b.adf",
    ]
    for path in cases:
        assert bool(re.fullmatch(staged, path)) == bool(amiga.FLOPPY_PATH.fullmatch(path)), path
    dump = re.search(r"\$DriveLine\s*= '([^']*)'", WINUAE_PS1).group(1)
    line = "DEBUG: drive 0 motor off cylinder  0 sel no rw mfmpos 0/12668"
    assert re.search(dump, line) and amiga.parse_drive_dump(line + "\nDEBUG: drive 1 motor  on "
                                                            "cylinder 12 sel yes ro mfmpos 5/9") == {0: "rw", 1: "ro"}
