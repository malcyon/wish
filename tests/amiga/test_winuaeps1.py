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
    assert PS1.count("Open-LanePipe $lane.proc.Id") == 5


def test_the_lane_pipe_is_chosen_by_its_server_pid():
    body = _body("Open-LanePipe")
    asked = body.index("GetNamedPipeServerProcessId")
    matched = body.index("$owner -eq $LanePid) { $script:LanePipeName = $name; return $try }", asked)
    assert asked < matched
    assert "$all = @('WinUAE') + (1..9 | ForEach-Object { \"WinUAE_$_\" })" in body


def test_a_lane_whose_pipe_is_nobody_s_is_named_with_every_server_seen():
    assert "no WinUAE pipe is served by this lane's winuae64 pid=$LanePid" in _body("Open-LanePipe")


def test_the_pipe_name_set_is_the_same_in_python_and_powershell():
    body = _body("Open-LanePipe")
    assert "'WinUAE'" in body and "(1..9" in body and "WinUAE_$_" in body
    assert amiga.LANE_PIPE_NAME.fullmatch("WinUAE")
    assert all(amiga.LANE_PIPE_NAME.fullmatch(f"WinUAE_{n}") for n in range(1, 10))
    assert not amiga.LANE_PIPE_NAME.fullmatch("WinUAE_10")


def test_the_pipe_search_waits_for_a_pipe_the_lane_has_not_made_yet():
    """The emulator can exist before its pipe does; the old fixed-name connect waited five seconds."""
    sig = re.search(r"function Open-LanePipe\(\[int\]\$LanePid, \[int\]\$WaitMs = (\d+)\)", PS1)
    assert sig and sig.group(1) == "5000"
    body = _body("Open-LanePipe")
    assert "while ($until.ElapsedMilliseconds -lt $WaitMs)" in body
    assert "Start-Sleep -Milliseconds 250" in body


def test_a_lone_pipe_and_an_unavailable_listing_keep_the_five_second_connect_for_winuae():
    body = _body("Open-LanePipe")
    assert "if ($names.Count -eq 1 -or ($null -eq $live -and $name -ceq 'WinUAE')) { 5000 } else { 2000 }" in body


def test_a_failed_listing_is_recorded_and_not_swallowed():
    body = _body("Open-LanePipe")
    assert "catch { }" not in body
    assert 'listing unavailable: $($_.Exception.Message)' in body


def test_the_no_pipe_message_names_the_listing_and_every_server_seen():
    body = _body("Open-LanePipe")
    assert "$listed; $($seen -join '; ')" in body
    assert "$name served by pid=$owner, skipped" in body


def test_a_wrong_server_verdict_names_the_pipe_that_was_opened():
    assert r"\\.\pipe\WinUAE is served" not in PS1
    assert PS1.count(r"fail \\.\pipe\$($script:LanePipeName) is served by pid=") == 2


def test_probing_another_copys_pipe_is_commented_where_it_happens():
    start = PS1.index("function Open-LanePipe")
    assert "nMaxInstances 1" in PS1[PS1.rindex("\n\n", 0, start):start]


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


def test_the_helper_preamble_takes_the_pid_and_counts_nothing():
    body = PS1[PS1.index("function Helper-Preamble"):PS1.index("$RaiseAndCheck = ")]
    assert "[string]$ReceiptPath, [int]$Id" in body
    assert "winuae64 processes" not in body and "Count -gt 1" not in body
    assert "Get-Process -Id $Id" in body
    assert "function Pid-Guard" not in PS1


def test_lane_one_keeps_the_names_a_run_in_flight_already_uses():
    body = _body("Lane-Paths")
    for name in ("winuae-claim.txt", "winuae-run.txt", "winuae-action.txt", "send.log",
                 "console.txt", "'winuae-run'", "'winuae-front'", "'winuae-key'", "'winuae-send'"):
        assert name in body, name


def test_the_lane_count_is_one_constant_in_one_place():
    assert PS1.count("$LaneCount = 1\n") == 1


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


def test_the_lane_verb_names_the_holders_lane_and_pid():
    valid = re.search(r"ValidateSet\(([^)]*)\)", PS1).group(1)
    assert "'lane'" in valid
    assert "ok lane=$ActiveLane pid=" in _case("lane")


def _case(name: str) -> str:
    """The text of one `switch ($Cmd)` branch."""
    start = PS1.index(f"  '{name}' {{")
    return PS1[start:PS1.index("\n  }\n", start)]


def test_start_writes_the_lane_ini_with_exactly_the_screenshot_keys():
    start = _case("start")
    for line in ("[WinUAE]", '"ScreenshotPath=$($LanePaths.shots)"', "'Screenshot_Original=1'",
                 "'Screenshot_Mode=1'", "'Screenshot_ClipMode=0'", '"MainPosX=$posX"', "'MainPosY=10'"):
        assert line in start
    assert "$posX = 10 + 740 * ($ActiveLane - 1)" in start
    assert "Set-Content -Path $LanePaths.ini -Encoding ASCII -ErrorAction Stop" in start
    written = start[start.index("@('[WinUAE]'"):start.index("| Set-Content -Path $LanePaths.ini")]
    assert written.count("=") == 6 and "Screenshot" in written


def test_start_empties_the_shots_folder_and_writes_the_ini_before_the_task_is_registered():
    start = _case("start")
    emptied = start.index("Get-ChildItem -Path $LanePaths.shots -Filter *.png | Remove-Item")
    assert start.index("New-Item -ItemType Directory -Force -Path $LanePaths.shots") < emptied
    assert emptied < start.index("Set-Content -Path $LanePaths.ini") < start.index("Register-Session1Task $LanePaths.task")


def test_start_launches_with_the_lane_ini_in_front_of_the_callers_arguments():
    start = _case("start")
    assert '$wanted = "-ini `"$($LanePaths.ini)`" " + ($Rest -join \' \')' in start
    assert "Register-Session1Task $LanePaths.task $Exe $wanted" in start
    assert "$expected = \"`\"$Exe`\" $wanted\"" in start


def test_every_lane_has_its_own_ini_and_shots_folder():
    paths = _body("Lane-Paths")
    assert '"$Root\\lanes\\1\\winuae.ini"' in paths and '"$Root\\lanes\\$n\\winuae.ini"' in paths
    assert '"$Root\\lanes\\1\\shots\\"' in paths and '"$Root\\lanes\\$n\\shots\\"' in paths


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
    assert "Open-LanePipe $lane.proc.Id" in finally_
    assert "$try -lt 2" in finally_
    assert "catch" in finally_
    assert "may still be held down" in finally_


def test_shot_discards_a_file_that_lands_just_after_a_no_new_file_failure():
    body = _body("Invoke-PipeVerb")
    start = body.index("$late = @()")
    section = body[start:body.index("wrote no file", start)]
    assert "Remove-Item" in section and "-cnotcontains" in section
    assert "discarded as stale" in section
