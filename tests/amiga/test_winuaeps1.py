"""`tools/amiga/winuae.ps1`'s snapshot verbs, read from the script that is deployed.

There is no `pwsh` here, so these tests read the script's text: they check what
it compares and the order it does things in, and the live run on #37 is the only
proof that the PowerShell behaves.
"""

from __future__ import annotations

import pathlib
import re

from automap import amiga

PS1_PATH = pathlib.Path(__file__).resolve().parents[2] / "tools" / "amiga" / "winuae.ps1"
PS1 = PS1_PATH.read_text()


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
    assert PS1.count("Open-LanePipe $lane.proc.Id") == 5


def test_the_lane_pipe_is_the_one_its_run_receipt_names_and_its_server_is_checked():
    body = _body("Open-LanePipe")
    assert "$run = Read-Kv $LanePaths.run" in body
    assert "$run['pipe']" in body
    asked = body.index("GetNamedPipeServerProcessId")
    thrown = body.index("is served by pid=$owner, not by this lane's winuae64 pid=$LanePid", asked)
    closed = body.index("Close-LanePipe $try", thrown)
    assert asked < thrown < closed


def test_the_lane_pipe_opener_opens_one_name_and_never_searches():
    body = _body("Open-LanePipe")
    for gone in ("1..9", "WinUAE_$_", "foreach", "do {", "$seen"):
        assert gone not in body, gone
    assert body.count("New-Object IO.Pipes.NamedPipeClientStream") == 1
    assert PS1.count("NamedPipeClientStream") == 1


def test_a_lane_without_a_recorded_pipe_or_with_a_gone_one_says_to_restart_it():
    body = _body("Open-LanePipe")
    assert "run receipt names no WinUAE pipe; stop the lane and start it again" in body
    assert "opened, is gone\"" in body
    assert "[IO.Directory]::GetFiles('\\\\.\\pipe\\')" in body


def test_the_pipe_name_set_is_the_same_in_python_and_powershell():
    name = amiga.LANE_PIPE_NAME.pattern
    assert name == "WinUAE(?:_[1-9])?"
    assert f"'^{name}\\z'" in _body("Open-LanePipe")
    assert name in _body("Read-LanePipeName")
    assert amiga.LANE_PIPE_NAME.fullmatch("WinUAE")
    assert all(amiga.LANE_PIPE_NAME.fullmatch(f"WinUAE_{n}") for n in range(1, 10))
    assert not amiga.LANE_PIPE_NAME.fullmatch("WinUAE_10")


def test_the_pipe_opener_keeps_its_signature_and_its_five_second_connect():
    sig = re.search(r"function Open-LanePipe\(\[int\]\$LanePid, \[int\]\$WaitMs = (\d+)\)", PS1)
    assert sig and sig.group(1) == "5000"
    assert "$try.Connect($WaitMs)" in _body("Open-LanePipe")


def test_a_pipe_is_closed_only_after_one_request_and_its_reply():
    body = _body("Close-LanePipe")
    guarded = body.index("-eq 'opened'")
    sent = body.index("Send-Pipe $Pipe 'CFG floppy0'", guarded)
    assert guarded < sent < body.index(".Dispose()")
    assert "$pipe.Dispose()" not in PS1 and "$try.Dispose()" not in PS1


def test_send_pipe_records_when_a_request_is_outstanding_and_answered():
    body = _body("Send-Pipe")
    assert body.index("$script:LanePipeState = 'sent'") < body.index("$Pipe.Write(")
    assert body.index("$script:LanePipeState = 'answered'") > body.index("while (-not $Pipe.IsMessageComplete)")


def test_start_waits_for_the_pipe_line_and_records_the_name_in_the_receipt():
    body = _case("start")
    released = body.index("$mutex.ReleaseMutex()")
    read = body.index("Read-LanePipeName", released)
    polled = body.index("Get-ReceiptProcess", read)
    slept = body.index("Start-Sleep -Milliseconds 500", polled)
    recorded = body.index("pipe    = $pipeName", slept)
    printed = body.index("ok pid=$($proc.Id) session=$($proc.SessionId) pipe=$pipeName", recorded)
    assert released < read < polled < slept < recorded < printed
    assert "$PipeLineBoundMs = 20000" in PS1
    assert "stop the lane and start it again" not in body[polled:]
    assert "wrote no IPC: Named Pipe line to" in body
    assert "exited before opening its pipe" in body


def test_the_boot_log_is_read_through_a_shared_handle_and_matched_on_its_pipe_line():
    body = _body("Read-LanePipeName")
    assert "[IO.FileShare]::ReadWrite" in body
    assert (r"'(?m)^IPC: Named Pipe ''\\\\\.\\pipe\\(WinUAE(?:_[1-9])?)'' open\r?$'") in body
    assert "throw" in body


def test_no_text_calls_probing_another_copys_pipe_harmless():
    docs = (PS1_PATH.parents[2] / "docs" / "143-winuae-debugger.md").read_text()
    for text in (PS1, pathlib.Path(amiga.__file__).read_text(), docs):
        for phrase in ("briefly occupies", "occupies it briefly", "only opened and closed"):
            assert phrase not in text, phrase


def test_the_pipe_rule_is_commented_where_the_pipe_is_opened():
    start = PS1.index("function Open-LanePipe")
    comment = " ".join(PS1[PS1.rindex("\n\n", 0, start):start].replace("#", " ").split())
    assert "close that pipe for good" in comment and "nothing here opens another lane's pipe" in comment


def test_a_wrong_server_verdict_names_the_pipe_that_was_opened():
    assert r"\\.\pipe\WinUAE is served" not in PS1
    assert PS1.count(r"fail \\.\pipe\$($script:LanePipeName) is served by pid=") == 2


# -- one emulator per lane, found by the pid in the lane's own receipt --------------

def _case(verb: str) -> str:
    """The text of one `switch ($Cmd)` branch."""
    switch = PS1.index("switch ($Cmd) {")
    start = PS1.index(f"\n  '{verb}' {{", switch)
    end = PS1.find("\n  '", start + 5)
    return PS1[start:end if end > 0 else len(PS1)]


def test_the_emulator_is_found_by_the_pid_in_the_lanes_receipt():
    body = _body("Resolve-MyEmulator")
    assert "Get-Process -Id" in body
    assert "-Name winuae64" not in body
    assert ".Count -gt 1" not in body


def test_the_script_has_no_key_or_front_verb_and_no_focus_helper():
    verbs = re.search(r"ValidateSet\(([^)]*)\)", PS1).group(1)
    assert "'key'" not in verbs and "'front'" not in verbs
    assert "\n  'key' {" not in PS1 and "\n  'front' {" not in PS1
    for word in ("RaiseAndCheck", "keybd_event", "SetForegroundWindow", "Invoke-Session1",
                 "Helper-Preamble", "$Extended", "-Extended", "winuae-front", "winuae-key"):
        assert word not in PS1, word
    assert "function Pid-Guard" not in PS1


def test_debugger_enters_over_the_pipe_with_no_key_or_window():
    verbs = re.search(r"ValidateSet\(([^)]*)\)", PS1).group(1)
    assert "'debugger'" in verbs
    assert "'debugger' { Invoke-PipeVerb 'debugger' }" in PS1
    body = _body("Invoke-PipeVerb")
    assert "'CFG AKS_ENTERDEBUGGER 1'" in body


def test_debugger_disposes_its_pipe_on_every_path_and_fails_unless_the_reply_is_404():
    body = _body("Invoke-PipeVerb")
    start = body.index("$Verb -ceq 'debugger'")
    section = body[start:body.index("$Verb -ceq 'press'", start)]
    assert "if ($r -cne '404') { $verdict = \"fail AKS_ENTERDEBUGGER replied $r\" }" in section
    assert "ok debugger entered" in section
    # One finally closes the pipe whether the send returned, failed or threw.
    tail = body[body.index("  } catch {", start):]
    assert "} finally {\n    if ($pipe) { Close-LanePipe $pipe }" in tail
    assert "if (-not $verdict.StartsWith('ok ', [StringComparison]::Ordinal)) { exit 1 }" in tail


def test_the_lane_checks_do_not_press_a_key_or_raise_a_window():
    for name in ("winuae-lanecheck.ps1", "winuae-sendcheck.ps1"):
        text = (PS1_PATH.parent / name).read_text()
        assert not re.search(r"Drive\s*\(?@?\(?\s*'?key\b", text), name
        assert not re.search(r"Drive\s*\(?@?\(?\s*'?front\b", text), name
        assert "7A" not in text and "F11" not in text, name
        assert "debugger" in text, name


def test_lane_one_keeps_the_names_a_run_in_flight_already_uses():
    body = _body("Lane-Paths")
    for name in ("winuae-claim.txt", "winuae-run.txt", "winuae-action.txt", "send.log",
                 "console.txt", "'winuae-run'", "'winuae-send'"):
        assert name in body, name


def test_the_lane_count_is_one_constant_in_one_place():
    assert len(re.findall(r"(?m)^\$LaneCount = \d+$", PS1)) == 1


def test_the_guest_runs_four_lanes():
    """Raised after four booted copies each held full speed and a four-lane lanecheck passed."""
    assert re.search(r"(?m)^\$LaneCount = 4$", PS1)


LANECHECK = (PS1_PATH.parent / "winuae-lanecheck.ps1").read_text()


def _lanecheck_body(function: str) -> str:
    start = LANECHECK.index(f"function {function}")
    return LANECHECK[start:LANECHECK.index("\n}\n", start)]


def test_the_lanecheck_runs_any_lane_count_against_a_driver_of_another_count():
    """The one-lane scenarios need a one-lane copy of a two-lane driver, and the other way round."""
    assert r"'(?m)^\$LaneCount = \d+\s*$'" in LANECHECK
    assert "-ne $Lanes" in LANECHECK


def test_the_lanecheck_needs_no_config_or_disk_the_guest_may_lack():
    """It writes its own two configs and blank disks, so `drives` reads a disk in each lane."""
    assert "pod-a500.uae" not in LANECHECK
    assert "$ConfigA = \"$Work\\driverA.uae\"" in LANECHECK and "$ConfigB = \"$Work\\driverB.uae\"" in LANECHECK
    setup = LANECHECK[:LANECHECK.index("$HasClaim")]
    assert "foreach ($i in 1..[Math]::Max(2, $Lanes))" in setup
    assert "Copy-Item $Machine $d.config" in setup and "WriteAllBytes($d.disk" in setup
    body = _lanecheck_body("Scenario-EveryLane")
    assert "\"floppy0=$($_.disk)\"" in body
    assert "Remove-Item -Recurse -Force $Work" in LANECHECK


def test_the_lanecheck_stops_the_lanes_then_deletes_its_files_on_any_exit_and_reports_a_failed_delete():
    """An emulator holding a file under the work directory makes the delete fail, and a throw must not skip it."""
    tail = LANECHECK[LANECHECK.index("\ntry {"):]
    final = tail[tail.index("} finally {"):]
    assert final.index("Reset-Lane") < final.index("Remove-Item -Recurse -Force $Work")
    assert "if (Test-Path $Work) {" in final and "if (Test-Path $Driver) {" in final
    assert "Scenario-EveryLane }" in tail[:tail.index("} finally {")]
    assert "if (Test-Path $HijackDriver) {" in final and "Remove-Item $HijackDriver" in final


def test_the_every_lane_scenario_drives_every_lane_and_blocks_one_holder_too_many():
    body = _lanecheck_body("Scenario-EveryLane")
    assert "1..$Lanes | ForEach-Object { Lane-Driver $_ }" in body
    assert "Drive @('claim', '-Holder', $_.holder)" in body
    assert "Drive @('claim', '-Holder', 'driverZ')" in body and "every Amiga lane is in use" in body
    assert "Sort-Object -Unique).Count -eq $Lanes" in body
    assert "Drive @('stop', '-Holder', $ds[1].holder)" in body
    assert "$q.StartTime -eq $began[$pids[$_]]" in body
    assert "Drive @('release', '-Holder', $_.holder)" in body
    assert "TwoLane" not in LANECHECK and "twolane" not in LANECHECK
    assert "'everylane'" in LANECHECK


def test_the_exclusive_scenario_checks_every_lane():
    body = _lanecheck_body("Scenario-Exclusive")
    assert body.count("1..$Lanes | ForEach-Object { Claim-Line $_ }") == 2
    assert "2..$Lanes | ForEach-Object { Claim-Line $_ }" in body
    assert "Claim-Line 2" not in body


def test_the_lanecheck_rejects_a_lane_count_outside_one_to_ten_before_it_writes_anything():
    guard = LANECHECK.index("if ($Lanes -lt 1 -or $Lanes -gt 10)")
    assert guard < LANECHECK.index("New-Item -ItemType Directory -Force -Path $Work")
    assert "function Lane-Driver" in LANECHECK[:guard]


def test_the_one_lane_wording_is_printed_only_when_there_is_one_lane():
    body = _case("claim")
    for text in ("; one Amiga lane at a time", "take the lane with: winuae.ps1 claim -Holder <id> -Override'"):
        for found in re.finditer(re.escape(text), body):
            assert "if ($LaneCount -eq 1)" in body[max(0, found.start() - 160):found.start()], text
    assert "-Override -Lane <n>" in body


def test_start_takes_the_guest_wide_mutex_before_it_launches_and_frees_it_in_a_finally():
    body = _case("start")
    mutex = body.index("Global\\wish-winuae-start")
    waited = body.index("WaitOne(", mutex)
    launched = body.index("Start-Session1Task $LanePaths.task", waited)
    released = body.index("ReleaseMutex()", launched)
    assert mutex < waited < launched < released
    assert "finally" in body[launched:released]
    assert "AbandonedMutexException" in body


def test_start_with_one_lane_blocks_on_any_winuae64_before_the_mutex():
    body = _case("start")
    before = body[:body.index("Global\\wish-winuae-start")]
    guard = before.index("if ($LaneCount -eq 1)")
    assert before.index("Get-Process -Name winuae64") > guard
    assert "winuae64 already running pid=$($any[0].Id); stop it first" in before


def test_stop_ends_the_task_even_when_the_receipt_resolves_to_nothing():
    body = _case("stop")
    head = body[:body.index("$mine = Resolve-MyEmulator")]
    assert "Stop-ScheduledTask -TaskName $LanePaths.task" in head
    assert "(Get-ScheduledTask -TaskName $LanePaths.task" in head


def test_start_owns_only_receipt_pids_that_resolve():
    body = _case("start")
    assert "(Get-ReceiptProcess $rr)) { $owned[" in body


def test_start_adopts_the_one_new_winuae64_that_no_lane_owns():
    body = _case("start")
    assert "$owned.ContainsKey" in body
    assert "Write-Kv $LanePaths.run" in body


def test_stop_ends_this_lanes_task_and_waits_on_its_pid():
    body = _case("stop")
    assert "Stop-ScheduledTask -TaskName $LanePaths.task" in body
    assert "$Task" not in body.replace("$LanePaths.task", "")
    assert "Get-Process -Name winuae64" not in body[body.index("$mine = Resolve-MyEmulator"):]


def test_roms_and_clean_look_at_every_lane():
    for verb in ("roms", "clean"):
        assert "1..$LaneCount" in _case(verb), verb
    assert "'winuae-*'" in _case("clean")


def test_send_gives_the_injector_this_lanes_log_and_console():
    body = _case("send")
    assert "-Log $($LanePaths.sendlog)" in body and "-Out $($LanePaths.console)" in body


def test_the_single_lane_denial_text_is_unchanged():
    assert "fail the WinUAE lane is claimed by $($c['holder']) since $($c['since']), not by $Holder" in PS1


def test_a_whole_desktop_claim_takes_every_lane_in_order():
    body = _case("claim")
    assert "$Exclusive" in body and "exclusive = 1" in body
    assert "1..$LaneCount" in body


def test_an_ordinary_claim_reads_the_reservation_before_its_candidate_loop():
    body = _case("claim")
    ordinary = body[body.index("$candidates ="):]
    assert ordinary.index("Get-Reservation") < ordinary.index("foreach ($n in $candidates)")
    assert "fail the WinUAE lanes are reserved for an exclusive claim" in ordinary
    assert "if (-not $Override)" in ordinary[:ordinary.index("Get-Reservation")]


def test_release_removes_the_callers_reservation():
    body = _case("release")
    assert "$ReservePath" in body and "-eq $Holder" in body[:body.index("Remove-Item $ReservePath")]
    assert body.index("Remove-Item $ReservePath") < body.index("$LaneCount -gt 1")
    assert r"winuae-exclusive.claim" in PS1


def test_a_waiting_exclusive_claim_keeps_its_lanes_and_never_gives_them_back():
    body = _case("claim")
    waiting = body[body.index("$Exclusive -and $WaitGiven"):body.index("if ($Exclusive -and $LaneCount -gt 1)")]
    assert "$until" in waiting and "$WaitSeconds" in waiting
    assert "Remove-Item $path" not in waiting.replace("if ($r['state'] -eq 'stale') { Remove-Item $path", "")
    assert "\"wait $Holder holds lanes" in waiting
    assert "Remove-Item $ReservePath" in waiting  # only once every lane is held


def test_a_whole_desktop_claim_without_wait_checks_the_reservation_first():
    body = _case("claim")
    plain = body[body.index("if ($Exclusive -and $LaneCount -gt 1)"):body.index("$candidates =")]
    assert plain.index("Get-Reservation") < plain.index("foreach ($n in 1..$LaneCount)")
    assert "reserved for an exclusive claim" in plain


def test_a_reservation_is_cleared_only_when_it_is_not_live():
    body = _case("claim")
    waiting = body[body.index("$Exclusive -and $WaitGiven"):body.index("if ($Exclusive -and $LaneCount -gt 1)")]
    assert "if ((Test-Path $ReservePath) -and -not (Get-Reservation)) { Remove-Item $ReservePath" in waiting
    assert "\n        Remove-Item $ReservePath -Force -ErrorAction SilentlyContinue\n        if (-not (Try-TakeClaim" not in waiting


def test_a_reservation_file_that_vanishes_mid_read_is_no_reservation():
    body = PS1[PS1.index("function Get-Reservation"):PS1.index("function Reservation-Text")]
    assert "if (-not $written) { return $null }" in body
    assert body.index("-not $written") < body.index("TotalSeconds")


def test_the_lane_verb_names_the_holders_lane_and_pid():
    valid = re.search(r"ValidateSet\(([^)]*)\)", PS1).group(1)
    assert "'lane'" in valid
    assert "ok lane=$ActiveLane pid=" in _case("lane")
    assert "pipe=$pipeName" in _case("lane")


def _case(name: str) -> str:
    """The text of one `switch ($Cmd)` branch."""
    start = PS1.index(f"  '{name}' {{")
    return PS1[start:PS1.index("\n  }\n", start)]


def _lane_ini_lines() -> str:
    """The array of lines `start` writes into the lane's ini."""
    start = _case("start")
    return start[start.index("@('[WinUAE]'"):start.index("| Set-Content -Path $LanePaths.ini")]


def test_start_writes_the_lane_ini_with_exactly_the_screenshot_and_path_keys():
    start = _case("start")
    for line in ("[WinUAE]", '"ScreenshotPath=$($LanePaths.shots)"', "'Screenshot_Original=1'",
                 "'Screenshot_Mode=1'", "'Screenshot_ClipMode=0'", '"MainPosX=$posX"', "'MainPosY=10'",
                 "'PathMode=WinUAE'", "'RelativePaths=0'"):
        assert line in start
    assert "$posX = 10 + 740 * ($ActiveLane - 1)" in start
    assert "Set-Content -Path $LanePaths.ini -Encoding ASCII -ErrorAction Stop" in start
    written = _lane_ini_lines()
    assert written.count("=") == 8 and "Screenshot" in written


def test_the_lane_ini_pins_absolute_paths_so_winuae_starts_from_the_lanes_working_directory():
    """Without PathMode WinUAE 6.0.3 turns -ini into relative paths taken from the
    task's working directory C:\\Amiga, lands one folder off and dies at start
    with 0xc0000409; PathMode=WinUAE with RelativePaths=0 started from there."""
    written = _lane_ini_lines()
    assert "'PathMode=WinUAE'" in written and "'RelativePaths=0'" in written
    assert "RelativePaths=1" not in written


def test_start_empties_the_shots_folder_and_writes_the_ini_before_the_task_is_registered():
    start = _case("start")
    emptied = start.index("Get-ChildItem -Path $LanePaths.shots -Filter *.png | Remove-Item")
    assert start.index("New-Item -ItemType Directory -Force -Path $LanePaths.shots") < emptied
    assert emptied < start.index("Set-Content -Path $LanePaths.ini") < start.index("Register-Session1Task $LanePaths.task")


def test_start_launches_with_the_lane_ini_and_data_folder_in_front_of_the_callers_arguments():
    start = _case("start")
    assert ('$wanted = "-ini `"$($LanePaths.ini)`" -datapath `"$(Split-Path $LanePaths.ini)`" " '
            "+ ($Rest -join ' ')") in start
    assert "Register-Session1Task $LanePaths.task $Exe $wanted" in start
    assert "$expected = \"`\"$Exe`\" $wanted\"" in start


def test_every_lane_has_its_own_ini_and_shots_folder():
    paths = _body("Lane-Paths")
    assert '"$Root\\lanes\\1\\winuae.ini"' in paths and '"$Root\\lanes\\$n\\winuae.ini"' in paths
    assert 'shots   = "$Root\\lanes\\1\\"' in paths and 'shots   = "$Root\\lanes\\$n\\"' in paths


def test_screenshots_are_looked_for_in_the_data_folder():
    """Under -datapath WinUAE 6.0.3 ignores the ini's ScreenshotPath and saves into its data folder,
    so the folder `shot` watches is the one `-datapath` names."""
    paths = _body("Lane-Paths")
    for lane in ("1", "$n"):
        assert f'shots   = "$Root\\lanes\\{lane}\\"' in paths
        assert f'ini     = "$Root\\lanes\\{lane}\\winuae.ini"' in paths
    assert "-datapath `\"$(Split-Path $LanePaths.ini)`\"" in _case("start")


def test_every_lane_has_its_own_boot_log_in_its_data_folder():
    """`-datapath` makes the lane folder WinUAE's data folder, which is where it writes its boot log."""
    paths = _body("Lane-Paths")
    assert 'bootlog = "$Root\\lanes\\1\\winuaebootlog.txt"' in paths
    assert 'bootlog = "$Root\\lanes\\$n\\winuaebootlog.txt"' in paths


def test_the_data_folder_argument_ends_without_a_backslash():
    """A trailing backslash before the closing quote escapes it, and WinUAE keeps its exe folder."""
    start = _case("start")
    wanted = start[start.index("$wanted = "):start.index("\n", start.index("$wanted = "))]
    assert "-datapath" in wanted and "\\`\"" not in wanted and "$LanePaths.shots" not in wanted


def test_start_deletes_the_lanes_old_boot_log_before_the_task_is_registered():
    start = _case("start")
    removed = start.index("if (Test-Path $LanePaths.bootlog) { Remove-Item $LanePaths.bootlog -ErrorAction Stop }")
    assert removed < start.index("Register-Session1Task $LanePaths.task")


def test_the_script_lists_shot_and_press_as_verbs():
    assert re.search(r"ValidateSet\([^)]*'shot'[^)]*'press'", PS1)
    assert "'shot' { Invoke-PipeVerb 'shot' }" in PS1 and "'press' { Invoke-PipeVerb 'press' }" in PS1


def test_shot_sends_one_screenshot_command_over_the_lanes_own_pipe_and_ownership_checks():
    body = _body("Invoke-PipeVerb")
    assert body.count("'DBG sc'") == 1
    assert body.index("Get-LaneEmulator") < body.index("Open-LanePipe $lane.proc.Id") < body.index("[Wish.PipeInfo]::") < body.index("$again = Get-LaneEmulator")


def test_shot_reads_only_a_file_that_was_not_there_before_the_command():
    body = _body("Invoke-PipeVerb")
    before = body.index("$before = @(Get-ChildItem")
    assert before < body.index("'DBG sc'") < body.index("$new = @(Get-ChildItem")
    assert "$before -cnotcontains $_.Name" in body
    assert "$new.Count -gt 1" in body
    assert "89504E470D0A1A0A" in body and "49454E44AE426082" in body


def test_shot_fails_clearly_at_the_999_file_limit_and_otherwise_on_a_missing_file():
    body = _body("Invoke-PipeVerb")
    assert "if ($last -ge 999)" in body
    assert "has written its 999 screenshots" in body
    assert "wrote no file" in body and "last counter" in body
    assert "$runKv['shots'] = [string]$counter" in body


def test_shot_resets_the_screenshot_counter_after_a_good_shot_and_never_before_one():
    body = _body("Invoke-PipeVerb")
    reset = body.index("'CFG SPC_SCREENSHOT 0'")
    assert body.count("SPC_SCREENSHOT") == 1
    assert body.index("'DBG sc'") < body.index("Remove-Item -Path $file.FullName") < reset
    assert reset < body.index('$verdict = "ok shot pid=')
    assert "try { [void](Send-Pipe $pipe 'CFG SPC_SCREENSHOT 0' 10000) } catch { }" in body


def test_shot_prints_the_markers_winvmguest_decodes():
    from tools.amiga import winvmguest
    body = _body("Invoke-PipeVerb")
    assert f"'{winvmguest.SHOT_BEGIN}'" in body and f"'{winvmguest.SHOT_END}'" in body
    assert 'ok shot pid=$($lane.proc.Id) counter=$counter ms=$ms' in body


def test_shot_does_not_crop_or_touch_the_desktop():
    body = _body("Invoke-PipeVerb")
    for word in ("CopyFromScreen", "System.Drawing", "Invoke-Session1", "RaiseAndCheck", "SetForegroundWindow"):
        assert word not in body


def test_press_holds_each_code_120_ms_and_releases_it_in_a_finally():
    body = _body("Invoke-PipeVerb")
    down = body.index('"CFG KEY_RAW_DOWN 0x$hex"')
    hold = body.index("Start-Sleep -Milliseconds 120")
    finally_ = body.index("} finally {", down)
    up = body.index('"CFG KEY_RAW_UP 0x$hex"')
    assert down < hold < finally_ < up
    assert "Start-Sleep -Milliseconds 150" in body


def test_press_validates_codes_and_splits_comma_lists():
    body = _body("Invoke-PipeVerb")
    assert "-split ','" in body
    assert "'^[0-9A-Fa-f]{2}\\z'" in body and "-gt 0x7F" in body and "$codes.Count -gt 16" in body
    assert "$r -cne '404'" in body


def test_no_screenshot_file_option_is_ever_sent():
    assert "AKS_SCREENSHOT_FILE" not in PS1


def test_one_lane_stop_without_a_receipt_fails_while_a_stranger_s_winuae64_remains():
    head = _case("stop")
    head = head[:head.index("$mine = Resolve-MyEmulator")]
    assert "if ($LaneCount -eq 1) {" in head
    tail = head[head.index("if ($LaneCount -eq 1) {"):]
    assert "Get-Process -Name winuae64" in tail
    assert "stop blocks an emulator it did not launch; pass -Override to end it anyway" in tail
    assert "fail winuae64 still running 10s after Stop-ScheduledTask" in tail
    assert tail.index("$Override") < tail.index("stop blocks an emulator")
    assert tail.index("exit 1") < tail.index("Remove-Item $LanePaths.run")


def test_stop_reads_the_task_state_again_after_the_wait_loop():
    head = _case("stop")
    head = head[:head.index("$mine = Resolve-MyEmulator")]
    loop_end = head.index("Start-Sleep -Milliseconds 250\n      }")
    after = head[loop_end:]
    assert "(Get-ScheduledTask -TaskName $LanePaths.task" in after
    assert after.index("(Get-ScheduledTask") < after.index("is still running 10s")


def test_press_releases_the_key_on_a_fresh_pipe_after_a_timed_out_down_and_retries():
    body = _body("Invoke-PipeVerb")
    finally_ = body[body.index("} finally {", body.index('"CFG KEY_RAW_DOWN')):]
    finally_ = finally_[:finally_.index("if (-not $verdict) {")]
    assert "} catch {" in body[body.index('"CFG KEY_RAW_DOWN'):body.index("} finally {", body.index('"CFG KEY_RAW_DOWN'))]
    assert "Close-LanePipe $pipe" in finally_
    assert finally_.index("Close-LanePipe $pipe") < finally_.index("Open-LanePipe $lane.proc.Id")
    assert "$try -lt 2" in finally_
    assert "catch" in finally_
    assert "may still be held down" in finally_


def test_shot_discards_a_file_that_lands_just_after_a_no_new_file_failure():
    body = _body("Invoke-PipeVerb")
    start = body.index("$late = @()")
    section = body[start:body.index("wrote no file", start)]
    assert "Remove-Item" in section and "-cnotcontains" in section
    assert "discarded as stale" in section


def test_the_console_route_enters_the_debugger_over_the_pipe_not_with_a_key():
    script = amiga.WinuaeDebugger("wish37", runner=lambda *_: "")._script(["m 0 1", "g"], [])
    assert "winuae.ps1 debugger -Holder wish37" in script
    assert "winuae.ps1 key" not in script
    assert not hasattr(amiga, "DEBUGGER_KEY")


def test_the_lanecheck_expects_the_lane_prefix_before_the_arguments_start_was_given():
    """`start` adds the lane's -ini and -datapath on every lane, so the args check must expect them."""
    body = _lanecheck_body("Scenario-Args")
    assert '-ini `"$laneDir\\winuae.ini`" -datapath `"$laneDir`" -log -f $ConfigB -s floppy0=' in body
    assert '$laneDir = "$Root\\lanes\\1"' in body


# -- the hijack scenario races on every round --------------------------------------

_PAUSE_ANCHOR = r"(?m)^([ \t]*)Start-Session1Task \$(LanePaths\.task|Task)[ \t\r]*$"


def test_start_adopts_only_a_new_winuae64_running_exactly_its_own_command_line():
    """The rule that stops a start from reporting another run's emulator as its own."""
    body = _case("start")
    assert "-eq ($expected -replace '\\s+', ' ').Trim()) { $matching += $cand }" in body
    assert "is running a command line this call did not pass" in body


def test_the_hijack_pause_lands_exactly_once_in_the_start_verb():
    """The check places its pause by text, so renaming the launch line has to fail here and not on the guest."""
    assert f"'{_PAUSE_ANCHOR}'" in LANECHECK
    found = list(re.finditer(_PAUSE_ANCHOR, PS1))
    assert len(found) == 1
    start = PS1.index("\n  'start' {", PS1.index("switch ($Cmd) {"))
    assert start < found[0].start() < PS1.index("\n  '", start + 5)


def test_the_hijack_round_lets_b_continue_only_after_a_replaced_its_emulator():
    body = _lanecheck_body("Scenario-Hijack")
    order = [body.index(s) for s in ("hijack-launched.txt", "Start-AsIntruder $ArgsA")]
    # The wait that follows the intruder, not the one for B's own emulator before it.
    order.append(body.index("-match [regex]::Escape($ConfigB)", order[1]))
    # The first go-file write in the body is the never-launched branch; the one that matters follows the wait.
    assert order[0] < order[1] < order[2]
    assert body.rindex("hijack-go.txt") > order[2]
    assert body.rindex("Receive-Job -Job $job") > body.rindex("hijack-go.txt")
    assert "LastRunTime" not in body
    assert "is running a command line this call did not pass" in body


def test_the_intruder_stops_and_waits_before_it_registers():
    body = _lanecheck_body("Start-AsIntruder")
    order = [body.index(s) for s in (
        "Stop-ScheduledTask", "'Running'", "Register-ScheduledTask", "Start-ScheduledTask")]
    assert order == sorted(order)


def test_the_lanecheck_control_breaks_only_the_command_line_match_of_its_own_copy():
    body = _lanecheck_body("New-HijackDriver")
    assert "if ($Control)" in body and "Set-Content -Path $HijackDriver" in body
    literal = re.search(r"\$exact = '(.*)'\n", body).group(1).replace("''", "'")
    assert PS1.count(literal) == 1


def test_the_control_exits_1_only_when_a_round_passes():
    body = _lanecheck_body("Scenario-Hijack")
    assert "as required" in body
    assert "$controlFailed -eq $HijackRounds" in body
    assert 'Verdict $false "control:' in body


def test_the_intruder_waits_for_b_to_be_running_before_it_acts():
    body = _lanecheck_body("Scenario-Hijack")
    wait = body.index("$ConfigB)", body.index("hijack-launched.txt", body.index("Test-Path")))
    assert wait < body.index("Start-AsIntruder $ArgsA")
    assert "never appeared" in body


def test_the_lanecheck_removes_a_leftover_hijack_job_on_any_exit():
    final = LANECHECK[LANECHECK.index("} finally {"):]
    assert "Remove-Job -Job $script:HijackJob" in final


def test_the_lanecheck_reads_every_lane_again_in_reverse_and_checks_the_pipes_are_still_listed():
    body = _lanecheck_body("Scenario-EveryLane")
    names = body.index("each start reports its own distinct pipe=")
    first = body.index("'drives', '-Holder', $d.holder")
    second = body.index("for ($n = $Lanes - 1; $n -ge 0; $n--)", first)
    again = body.index("'drives', '-Holder', $ds[$n].holder", second)
    listed = body.index("[IO.Directory]::GetFiles('\\\\.\\pipe\\')", again)
    assert names < first < second < again < listed
    assert "$listed -cnotcontains $_" in body
    assert "pipe=$($pipes[$n])" in body


def test_a_throw_after_connecting_closes_the_pipe_through_close_lane_pipe():
    body = _body("Open-LanePipe")
    connected = body.index("$try.Connect($WaitMs)")
    guarded = body.index("try {", connected)
    assert guarded < body.index("$try.ReadMode =") < body.index("GetNamedPipeServerProcessId")
    handler = body.index("} catch {", guarded)
    assert body.index("Close-LanePipe $try", handler) < body.index("throw", handler)
    assert "Close-LanePipe $try\n    throw\n" in body[handler:]


def test_exclusive_waiters_are_served_in_the_order_they_arrived():
    """The head of a name-sorted queue is decided before the reservation, so a later poll cannot jump it."""
    assert "winuae-exclusive-queue" in PS1
    head = _body("Get-QueueHead")
    assert "Sort-Object Name" in head
    assert "Remove-Item $f.FullName" in head
    assert "{0:D20}-{1}.wait" in PS1 and "[DateTime]::UtcNow.Ticks" in PS1

    body = _case("claim")
    waiting = body[body.index("$Exclusive -and $WaitGiven"):body.index("if ($Exclusive -and $LaneCount -gt 1)")]
    assert waiting.index("Try-TakeClaim (Join-Path $QueueDir") < waiting.index("Get-QueueHead")
    assert waiting.index("Get-QueueHead") < waiting.index("Get-Reservation")
    start = waiting.index("if ($head -and $head['holder'] -ne $Holder) {")
    queued = waiting[start:waiting.index("\n", waiting.index("}", waiting.index("exit", start)))]
    assert "is queued behind $($head['holder'])" in queued
    assert "exit 0" in queued and "exit 1" not in queued
    remove = _body("Remove-QueueTicket")
    assert "foreach ($f in" in remove and "Remove-Item $f.FullName" in remove
    assert "Get-QueueTicket" not in remove
    assert waiting.index("Remove-QueueTicket $Holder") > waiting.index("Remove-Item $ReservePath")
    assert "Remove-QueueTicket $Holder" in _case("release")
    assert "Waiters are served in arrival order" in PS1[:PS1.index("param(")]


def test_a_second_ordinary_claim_by_its_holder_writes_nothing():
    claim = _case("claim")
    ordinary = claim[claim.index("$candidates = if ($Override"):]
    reuse = ordinary.index("(already yours since $($r['claim']['since']))")
    assert "exit 0" in ordinary[reuse:reuse + 120]
    assert reuse < ordinary.index("Try-TakeClaim")
    race = ordinary[ordinary.index("for ($m = 1; $m -lt $n; $m++)"):]
    assert "Remove-Item $path" in race[:race.index("exit 0")]
