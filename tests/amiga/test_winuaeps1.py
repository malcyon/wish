"""`tools/amiga/winuae.ps1`'s snapshot verbs, read from the script that is deployed.

There is no `pwsh` here, so these tests read the script's text: they check what
it compares and the order it does things in, and the live run on #37 is the only
proof that the PowerShell behaves.
"""

from __future__ import annotations

import pathlib
import re

from automap import amiga

PS1 = (pathlib.Path(__file__).resolve().parents[2] / "tools" / "amiga" / "winuae.ps1").read_text()


def _body(function: str) -> str:
    start = PS1.index(f"function {function}")
    return PS1[start:PS1.index("\n}\n", start)]


def test_the_device_name_pattern_is_the_same_in_python_and_powershell():
    """Python blocks a device name before the guest sees it; the guest must block the same set."""
    found = re.search(r"\$Text -imatch '(.+)'", _body("Test-DeviceName"))
    assert found, "Test-DeviceName has no -imatch pattern"
    guest = found.group(1)
    assert guest.startswith("^") and guest.endswith(r"\z")
    python = amiga.WINDOWS_DEVICE.pattern
    assert python.startswith("(?i)")
    # PowerShell's -imatch is case-insensitive and unanchored; Python's is fullmatched.
    assert guest[1:-2] == python[4:].replace("(?:", "(")


def test_a_failed_key_value_write_stops_the_script():
    assert "Set-Content -Path $Path -Encoding ASCII -ErrorAction Stop" in _body("Write-Kv")


def test_the_marker_is_checked_before_the_old_snapshot_is_replaced():
    body = _body("Invoke-State")
    written = body.index('Write-Kv "$part\\complete~"')
    checked = body.index('Test-Path -LiteralPath "$part\\complete~" -PathType Leaf', written)
    replaced = body.index("Replace-StateFolder $part $dir $backup", checked)
    assert written < checked < replaced


def test_a_failed_move_back_names_where_the_old_snapshot_is():
    body = _body("Replace-StateFolder")
    back = body.index("Move-Item -LiteralPath $Backup -Destination $Dir -ErrorAction Stop")
    named = body.index("so it is in $Backup", back)
    assert back < named


def test_every_pipe_verb_opens_the_pipe_its_own_emulator_serves():
    """Two copies make `WinUAE` possibly the other lane's pipe, so no verb names one."""
    assert "'WinUAE', 'InOut'" not in PS1
    assert PS1.count("Open-LanePipe $lane.proc.Id") == 3


def test_the_lane_pipe_is_chosen_by_its_server_pid():
    body = _body("Open-LanePipe")
    asked = body.index("GetNamedPipeServerProcessId")
    matched = body.index("-eq $LanePid) { return $try }", asked)
    assert asked < matched
    assert "$names = @('WinUAE') + (1..9 | ForEach-Object { \"WinUAE_$_\" })" in body


def test_a_lane_whose_pipe_is_nobody_s_is_named_with_every_server_seen():
    assert "no WinUAE pipe is served by this lane's winuae64 pid=$LanePid" in _body("Open-LanePipe")


def test_the_pipe_name_set_is_the_same_in_python_and_powershell():
    body = _body("Open-LanePipe")
    assert "'WinUAE'" in body and "(1..9" in body and "WinUAE_$_" in body
    assert amiga.LANE_PIPE_NAME.fullmatch("WinUAE")
    assert all(amiga.LANE_PIPE_NAME.fullmatch(f"WinUAE_{n}") for n in range(1, 10))
    assert not amiga.LANE_PIPE_NAME.fullmatch("WinUAE_10")
